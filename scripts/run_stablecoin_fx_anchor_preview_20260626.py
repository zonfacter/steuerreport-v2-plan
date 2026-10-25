#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.contracts.prices import PricePointCreate  # noqa: E402
from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.tax import TaxService  # noqa: E402
from steuerreport_v2.domain.valuation import PriceQualityService  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_V1_DB = Path(str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db")))
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "stablecoin_fx_anchor_preview"
ANCHOR_SOURCE_PREFIX = "stablecoin_fx_anchor:v1_fx_cache"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Stablecoin-FX anchor preview from the V1 USD/EUR FX cache. "
            "Optionally simulates FIFO/tax impact on temporary DuckDB copies."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--v1-db", default=str(DEFAULT_V1_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--days-per-group", type=int, default=1000)
    parser.add_argument("--tax-impact", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    v1_db_path = Path(args.v1_db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    service = PriceQualityService(DuckDbStore(db_path))
    replacement_preview = service.stablecoin_fx_replacement_preview(
        limit=args.limit,
        days_per_group=args.days_per_group,
    )
    anchor_plan = build_anchor_plan(
        replacement_preview.model_dump(mode="json"),
        v1_db_path=v1_db_path,
    )
    impact = (
        simulate_tax_impact(db_path=db_path, anchor_plan=anchor_plan)
        if args.tax_impact
        else []
    )

    report = {
        "mode": "read-only_preview",
        "generated_at": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "v1_db_path": str(v1_db_path),
        "anchor_source_prefix": ANCHOR_SOURCE_PREFIX,
        "summary": summarize_anchor_plan(anchor_plan),
        "anchors": anchor_plan,
        "tax_impact": impact,
        "tax_impact_summary": summarize_tax_impact(impact),
        "methodology": (
            "Only Stablecoin-FX replacement_needed days from the live price-quality preview are used. "
            "For each day the script reads USD/EUR from the V1 sqlite fx_cache and plans an "
            "asset price equal to that USD/EUR rate, because USDT/BUSD are treated as USD-parity "
            "stablecoins for this quality closure. The live DuckDB is never written. When "
            "--tax-impact is enabled, anchors and derived-price replacements are applied only to "
            "temporary database copies before FIFO is rebuilt."
        ),
    }

    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_stablecoin_fx_anchor_preview.json"
    latest_path = output_dir / "latest_stablecoin_fx_anchor_preview.json"
    payload = json.dumps(report, indent=2, ensure_ascii=False, default=json_default)
    output_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "latest_path": str(latest_path),
                "summary": report["summary"],
                "tax_impact_summary": report["tax_impact_summary"],
            },
            indent=2,
            ensure_ascii=False,
            default=json_default,
        )
    )


def build_anchor_plan(preview: dict[str, Any], *, v1_db_path: Path) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for group in preview.get("groups", []):
        for day in group.get("days", []):
            if day.get("replacement_status") != "replacement_needed":
                continue
            asset = str(day["asset"]).upper()
            price_date = str(day["price_date"])
            key = (asset, int(day["year"]), price_date, str(day["source"]))
            candidates[key] = {
                "asset": asset,
                "year": int(day["year"]),
                "price_date": price_date,
                "source": str(day["source"]),
                "tax_lines_count": int(day.get("tax_lines_count") or 0),
                "tax_quantity": str(day.get("tax_quantity") or "0"),
                "derived_price_count": int(day.get("derived_price_count") or 0),
                "min_derived_price_eur": str(day.get("min_derived_price_eur")),
                "max_derived_price_eur": str(day.get("max_derived_price_eur")),
                "sample_event_refs": list(day.get("sample_event_refs") or [])[:5],
            }

    if not candidates:
        return []
    if not v1_db_path.exists():
        return [
            {
                **candidate,
                "anchor_status": "missing_v1_db",
                "price_point": None,
                "recommended_action": "V1-FX-Datenbank bereitstellen, bevor ein Replacement geplant wird.",
            }
            for candidate in sorted(candidates.values(), key=_anchor_sort_key)
        ]

    anchors: list[dict[str, Any]] = []
    with sqlite3.connect(f"file:{v1_db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        for candidate in sorted(candidates.values(), key=_anchor_sort_key):
            fx = read_usd_eur_fx(con, candidate["price_date"])
            if fx is None:
                anchors.append(
                    {
                        **candidate,
                        "anchor_status": "missing_usd_eur_fx",
                        "price_point": None,
                        "recommended_action": "USD/EUR-FX-Kurs fuer diesen Tag beschaffen.",
                    }
                )
                continue
            rate = Decimal(str(fx["rate"]))
            source = (
                f"{ANCHOR_SOURCE_PREFIX}:{fx['source']}:"
                f"rate_date:{fx['rate_date']}:source_rate_date:{fx['source_rate_date']}"
            )
            anchors.append(
                {
                    **candidate,
                    "anchor_status": "ready",
                    "usd_eur": format(rate, "f"),
                    "fx_source": str(fx["source"]),
                    "fx_rate_date": str(fx["rate_date"]),
                    "fx_source_rate_date": str(fx["source_rate_date"]),
                    "price_point": {
                        "asset": candidate["asset"],
                        "price_eur": format(rate, "f"),
                        "priced_at": f"{candidate['price_date']}T00:00:00+00:00",
                        "source": source,
                        "confidence": "1.0",
                    },
                    "recommended_action": (
                        "Als Stablecoin-FX-Anker verwendbar; vor Live-Import erst Tax-Impact "
                        "und Review-Decision dokumentieren."
                    ),
                }
            )
    return anchors


def read_usd_eur_fx(con: sqlite3.Connection, price_date: str) -> sqlite3.Row | None:
    return con.execute(
        """
        select rate_date, base_ccy, quote_ccy, rate, source, source_rate_date
        from fx_cache
        where rate_date = ? and base_ccy = 'USD' and quote_ccy = 'EUR'
        limit 1
        """,
        [price_date],
    ).fetchone()


def summarize_anchor_plan(anchors: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, dict[str, Any]] = {}
    for row in anchors:
        key = f"{row['asset']}:{row['year']}"
        item = by_group.setdefault(
            key,
            {
                "asset": row["asset"],
                "year": row["year"],
                "required_days": 0,
                "ready_days": 0,
                "missing_days": 0,
                "tax_lines_count": row["tax_lines_count"],
            },
        )
        item["required_days"] += 1
        if row["anchor_status"] == "ready":
            item["ready_days"] += 1
        else:
            item["missing_days"] += 1
    return {
        "required_days": len(anchors),
        "ready_days": sum(1 for row in anchors if row["anchor_status"] == "ready"),
        "missing_days": sum(1 for row in anchors if row["anchor_status"] != "ready"),
        "groups": sorted(by_group.values(), key=lambda row: (row["asset"], row["year"])),
    }


def simulate_tax_impact(*, db_path: Path, anchor_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = [row for row in anchor_plan if row["anchor_status"] == "ready"]
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in ready:
        grouped[(row["asset"], row["year"], row["source"])].append(row)

    impacts: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="steuerreport_stablecoin_fx_anchor_") as tmp:
        tmp_dir = Path(tmp)
        for (asset, year, source), anchors in sorted(grouped.items()):
            baseline_db = tmp_dir / f"baseline_{asset}_{year}_{db_path.name}"
            patched_db = tmp_dir / f"patched_{asset}_{year}_{db_path.name}"
            shutil.copy2(db_path, baseline_db)
            shutil.copy2(db_path, patched_db)

            baseline = rebuild_and_totals(baseline_db, year=year, stable_asset=asset)
            inserted_anchors = insert_anchor_price_points(patched_db, anchors)
            replacement_plan = replacement_rows(patched_db, asset=asset, year=year, source=source)
            applied_replacements = apply_replacements(patched_db, replacement_plan)
            patched = rebuild_and_totals(patched_db, year=year, stable_asset=asset)
            impacts.append(
                {
                    "asset": asset,
                    "year": year,
                    "source": source,
                    "anchor_days": len(anchors),
                    "inserted_anchor_prices": inserted_anchors,
                    "replacement_ready_rows": sum(
                        1 for row in replacement_plan if row["replacement_status"] == "ready"
                    ),
                    "replacement_missing_rows": sum(
                        1 for row in replacement_plan if row["replacement_status"] != "ready"
                    ),
                    "applied_replacements": applied_replacements,
                    "baseline": baseline,
                    "patched": patched,
                    "delta": diff_totals(baseline, patched),
                    "conclusion": conclusion(baseline, patched, replacement_plan),
                }
            )
    return impacts


def replacement_rows(db_path: Path, *, asset: str, year: int, source: str) -> list[dict[str, Any]]:
    report = PriceQualityService(DuckDbStore(db_path)).stablecoin_fx_replacement_impact(
        asset=asset,
        year=year,
        source=source,
        limit=10_000,
    )
    return [row.model_dump(mode="json") for row in report.rows]


def insert_anchor_price_points(db_path: Path, anchors: list[dict[str, Any]]) -> int:
    points: list[PricePointCreate] = []
    for anchor in anchors:
        payload = anchor["price_point"]
        points.append(
            PricePointCreate(
                asset=payload["asset"],
                price_eur=Decimal(str(payload["price_eur"])),
                priced_at=datetime.combine(
                    datetime.fromisoformat(anchor["price_date"]).date(),
                    time.min,
                    tzinfo=UTC,
                ),
                source=payload["source"],
                confidence=Decimal(str(payload["confidence"])),
            )
        )
    DuckDbStore(db_path).add_price_points(points)
    return len(points)


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


def summarize_tax_impact(impact: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "groups_count": len(impact),
        "groups_requiring_review": sum(
            1
            for row in impact
            if row["conclusion"] == "replacement_changes_tax_result_review_required"
        ),
        "groups_complete_quality_only": sum(
            1
            for row in impact
            if row["conclusion"] == "no_tax_delta_replacement_is_quality_closure_only"
        ),
        "groups_incomplete": sum(
            1 for row in impact if row["conclusion"] == "replacement_not_complete"
        ),
        "taxable_gain_loss_delta_eur": str(
            sum(
                Decimal(str(row["delta"].get("taxable_gain_loss_eur", "0")))
                for row in impact
            )
        ),
    }


def _anchor_sort_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return str(row["asset"]), int(row["year"]), str(row["price_date"])


def json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    main()
