#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "disposal_trade_evidence_audits"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only BMF/FIFO evidence audit for disposal/trade tax lines. "
            "Exports annual summaries and top 2024 gain/loss evidence rows."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--focus-year", type=int, default=2024)
    parser.add_argument("--top-limit", type=int, default=80)
    parser.add_argument(
        "--live-db",
        action="store_true",
        help="Read the DuckDB file directly. By default a temporary snapshot copy is used to avoid API locks.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    audit_db_path = db_path
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if not args.live_db:
        temp_dir = tempfile.TemporaryDirectory(prefix="steuerreport_disposal_audit_")
        audit_db_path = Path(temp_dir.name) / db_path.name
        shutil.copy2(db_path, audit_db_path)
    try:
        with duckdb.connect(str(audit_db_path), read_only=True) as con:
            annual_rows = annual_status(con)
            top_rows = top_evidence_rows(con, year=args.focus_year, limit=max(1, args.top_limit))
            quality_rows = price_quality_summary(con)
            unmatched_rows = unmatched_disposal_summary(con)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    report = {
        "mode": "read-only",
        "generated_at": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "audit_db_mode": "live" if args.live_db else "temporary_snapshot_copy",
        "focus_year": args.focus_year,
        "summary": {
            "years_count": len(annual_rows),
            "focus_year_top_rows": len(top_rows),
            "unmatched_disposals_count": sum(int(row["unmatched_count"]) for row in unmatched_rows),
            "missing_any_price_years": [
                row["year"]
                for row in annual_rows
                if int(row["acquisition_missing_price_count"]) or int(row["disposal_missing_price_count"])
            ],
            "missing_raw_evidence_years": [
                row["year"]
                for row in annual_rows
                if int(row["acquisition_raw_missing_count"]) or int(row["disposal_raw_missing_count"])
            ],
        },
        "annual_status": annual_rows,
        "price_quality_summary": quality_rows,
        "unmatched_disposals": unmatched_rows,
        "focus_year_top_lines": top_rows,
        "methodology": (
            "Read-only audit from tax_lines, tax_lots, canonical_events and price_ledger. "
            "Taxable means holding_days <= 365, matching the existing V2 tax-year logic. "
            "Price checks distinguish missing at-or-before price, missing same-day primary price, "
            "derived/event-quote valuation and stale at-or-before lookup. The report does not "
            "recalculate FIFO and does not write prices or tax data."
        ),
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"{run_id}_disposal_trade_evidence_audit.json"
    latest_json_path = output_dir / "latest_disposal_trade_evidence_audit.json"
    csv_path = output_dir / f"{run_id}_{args.focus_year}_top_disposal_trade_lines.csv"
    latest_csv_path = output_dir / f"latest_{args.focus_year}_top_disposal_trade_lines.csv"
    json_payload = json.dumps(report, indent=2, ensure_ascii=False, default=json_default)
    json_path.write_text(json_payload, encoding="utf-8")
    latest_json_path.write_text(json_payload, encoding="utf-8")
    write_top_rows_csv(csv_path, top_rows)
    write_top_rows_csv(latest_csv_path, top_rows)
    print(
        json.dumps(
            {
                "output_path": str(json_path),
                "latest_path": str(latest_json_path),
                "top_csv_path": str(csv_path),
                "latest_top_csv_path": str(latest_csv_path),
                "summary": report["summary"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def annual_status(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        with line_context as (
            select
                date_part('year', l.disposed_at)::integer as year,
                l.tax_line_id,
                l.asset,
                l.holding_days,
                l.quantity,
                l.acquisition_cost_eur,
                l.disposal_proceeds_eur,
                l.gain_loss_eur,
                lot.acquired_at,
                l.disposed_at,
                ae.raw_object_id as acquisition_raw_object_id,
                de.raw_object_id as disposal_raw_object_id,
                upper(coalesce(ae.quote_asset, l.asset)) as acquisition_price_asset,
                upper(coalesce(de.quote_asset, l.asset)) as disposal_price_asset,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then 1 else ap.price_eur end as acquisition_price_eur,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then 'fiat:eur' else ap.source end as acquisition_price_source,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then lot.acquired_at else ap.priced_at end as acquisition_priced_at,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then 1 else dp.price_eur end as disposal_price_eur,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then 'fiat:eur' else dp.source end as disposal_price_source,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then l.disposed_at else dp.priced_at end as disposal_priced_at,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then true else exists (
                    select 1
                    from price_ledger p
                    where upper(p.asset) = upper(coalesce(ae.quote_asset, l.asset))
                      and p.price_eur > 0
                      and cast(p.priced_at as date) = cast(lot.acquired_at as date)
                      and lower(p.source) not like 'derived:%'
                ) end as acquisition_same_day_primary,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then true else exists (
                    select 1
                    from price_ledger p
                    where upper(p.asset) = upper(coalesce(de.quote_asset, l.asset))
                      and p.price_eur > 0
                      and cast(p.priced_at as date) = cast(l.disposed_at as date)
                      and lower(p.source) not like 'derived:%'
                ) end as disposal_same_day_primary
            from tax_lines l
            join tax_lots lot on lot.lot_id = l.lot_id
            left join canonical_events ae on ae.event_id = lot.source_event_id
            left join canonical_events de on de.event_id = l.source_event_id
            left join lateral (
                select price_eur, source, priced_at
                from price_ledger p
                where upper(p.asset) = upper(coalesce(ae.quote_asset, l.asset))
                  and p.price_eur > 0
                  and p.priced_at <= lot.acquired_at
                order by p.priced_at desc, p.created_at desc
                limit 1
            ) ap on true
            left join lateral (
                select price_eur, source, priced_at
                from price_ledger p
                where upper(p.asset) = upper(coalesce(de.quote_asset, l.asset))
                  and p.price_eur > 0
                  and p.priced_at <= l.disposed_at
                order by p.priced_at desc, p.created_at desc
                limit 1
            ) dp on true
        )
        select
            year,
            count(*) as tax_lines_count,
            count(*) filter (where holding_days <= 365) as taxable_lines_count,
            count(*) filter (where holding_days > 365) as tax_free_lines_count,
            sum(disposal_proceeds_eur) as gross_disposal_proceeds_eur,
            sum(acquisition_cost_eur) as acquisition_cost_eur,
            sum(gain_loss_eur) as gain_loss_eur,
            sum(case when holding_days <= 365 then gain_loss_eur else 0 end) as taxable_gain_loss_eur,
            sum(case when holding_days > 365 then gain_loss_eur else 0 end) as tax_free_gain_loss_eur,
            count(*) filter (where acquisition_raw_object_id is null) as acquisition_raw_missing_count,
            count(*) filter (where disposal_raw_object_id is null) as disposal_raw_missing_count,
            count(*) filter (where acquisition_price_eur is null) as acquisition_missing_price_count,
            count(*) filter (where disposal_price_eur is null) as disposal_missing_price_count,
            count(*) filter (where not acquisition_same_day_primary) as acquisition_missing_same_day_primary_count,
            count(*) filter (where not disposal_same_day_primary) as disposal_missing_same_day_primary_count,
            count(*) filter (where lower(coalesce(acquisition_price_source, '')) like 'derived:%') as acquisition_derived_price_count,
            count(*) filter (where lower(coalesce(disposal_price_source, '')) like 'derived:%') as disposal_derived_price_count,
            count(*) filter (
                where acquisition_priced_at is not null
                  and date_diff('day', cast(acquisition_priced_at as date), cast(acquired_at as date)) > 7
            ) as acquisition_stale_price_count,
            count(*) filter (
                where disposal_priced_at is not null
                  and date_diff('day', cast(disposal_priced_at as date), cast(disposed_at as date)) > 7
            ) as disposal_stale_price_count
        from line_context
        group by year
        order by year
        """
    ).fetchall()
    columns = [
        "year",
        "tax_lines_count",
        "taxable_lines_count",
        "tax_free_lines_count",
        "gross_disposal_proceeds_eur",
        "acquisition_cost_eur",
        "gain_loss_eur",
        "taxable_gain_loss_eur",
        "tax_free_gain_loss_eur",
        "acquisition_raw_missing_count",
        "disposal_raw_missing_count",
        "acquisition_missing_price_count",
        "disposal_missing_price_count",
        "acquisition_missing_same_day_primary_count",
        "disposal_missing_same_day_primary_count",
        "acquisition_derived_price_count",
        "disposal_derived_price_count",
        "acquisition_stale_price_count",
        "disposal_stale_price_count",
    ]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def top_evidence_rows(con: duckdb.DuckDBPyConnection, *, year: int, limit: int) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        with ranked as (
            select
                l.tax_line_id,
                l.asset,
                l.disposed_at,
                l.quantity,
                l.acquisition_cost_eur,
                l.disposal_proceeds_eur,
                l.gain_loss_eur,
                l.holding_days,
                l.lot_id,
                lot.acquired_at,
                lot.source_event_id as acquisition_event_id,
                l.source_event_id as disposal_event_id,
                ae.source as acquisition_source,
                ae.event_type as acquisition_event_type,
                ae.quote_asset as acquisition_quote_asset,
                ae.quote_quantity as acquisition_quote_quantity,
                ae.raw_object_id as acquisition_raw_object_id,
                ae.source_ref as acquisition_source_ref,
                ae.tx_id as acquisition_tx_id,
                de.source as disposal_source,
                de.event_type as disposal_event_type,
                de.quote_asset as disposal_quote_asset,
                de.quote_quantity as disposal_quote_quantity,
                de.raw_object_id as disposal_raw_object_id,
                de.source_ref as disposal_source_ref,
                de.tx_id as disposal_tx_id,
                de.account as disposal_account,
                upper(coalesce(ae.quote_asset, l.asset)) as acquisition_price_asset,
                upper(coalesce(de.quote_asset, l.asset)) as disposal_price_asset,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then 1 else ap.price_eur end as acquisition_price_eur,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then 'fiat:eur' else ap.source end as acquisition_price_source,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then lot.acquired_at else ap.priced_at end as acquisition_priced_at,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then 1 else dp.price_eur end as disposal_price_eur,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then 'fiat:eur' else dp.source end as disposal_price_source,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then l.disposed_at else dp.priced_at end as disposal_priced_at,
                case when upper(coalesce(ae.quote_asset, l.asset)) = 'EUR' then true else exists (
                    select 1
                    from price_ledger p
                    where upper(p.asset) = upper(coalesce(ae.quote_asset, l.asset))
                      and p.price_eur > 0
                      and cast(p.priced_at as date) = cast(lot.acquired_at as date)
                      and lower(p.source) not like 'derived:%'
                ) end as acquisition_same_day_primary,
                case when upper(coalesce(de.quote_asset, l.asset)) = 'EUR' then true else exists (
                    select 1
                    from price_ledger p
                    where upper(p.asset) = upper(coalesce(de.quote_asset, l.asset))
                      and p.price_eur > 0
                      and cast(p.priced_at as date) = cast(l.disposed_at as date)
                      and lower(p.source) not like 'derived:%'
                ) end as disposal_same_day_primary,
                row_number() over (order by l.gain_loss_eur desc, l.disposed_at, l.tax_line_id) as gain_rank,
                row_number() over (order by l.gain_loss_eur asc, l.disposed_at, l.tax_line_id) as loss_rank,
                row_number() over (order by abs(l.gain_loss_eur) desc, l.disposed_at, l.tax_line_id) as abs_rank
            from tax_lines l
            join tax_lots lot on lot.lot_id = l.lot_id
            left join canonical_events ae on ae.event_id = lot.source_event_id
            left join canonical_events de on de.event_id = l.source_event_id
            left join lateral (
                select price_eur, source, priced_at
                from price_ledger p
                where upper(p.asset) = upper(coalesce(ae.quote_asset, l.asset))
                  and p.price_eur > 0
                  and p.priced_at <= lot.acquired_at
                order by p.priced_at desc, p.created_at desc
                limit 1
            ) ap on true
            left join lateral (
                select price_eur, source, priced_at
                from price_ledger p
                where upper(p.asset) = upper(coalesce(de.quote_asset, l.asset))
                  and p.price_eur > 0
                  and p.priced_at <= l.disposed_at
                order by p.priced_at desc, p.created_at desc
                limit 1
            ) dp on true
            where date_part('year', l.disposed_at)::integer = ?
              and l.holding_days <= 365
        )
        select *
        from ranked
        where gain_rank <= ? or loss_rank <= ? or abs_rank <= ?
        order by abs(gain_loss_eur) desc, disposed_at, tax_line_id
        """,
        [year, limit, limit, limit],
    ).fetchall()
    columns = [item[0] for item in con.description]
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(columns, row, strict=True))
        item["review_reasons"] = review_reasons(item)
        item["tax_treatment"] = "taxable_private_disposal_fifo"
        item["asset_fifo_drilldown_endpoint"] = (
            f"/api/v1/tax-years/{year}/asset-fifo-drilldown?asset={item['asset']}"
        )
        result.append(item)
    return result


def price_quality_summary(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        select
            upper(asset) as asset,
            date_part('year', disposed_at)::integer as year,
            count(*) as tax_lines_count,
            sum(disposal_proceeds_eur) as proceeds_eur,
            sum(gain_loss_eur) as gain_loss_eur,
            count(*) filter (where holding_days <= 365) as taxable_lines_count,
            count(*) filter (where holding_days > 365) as tax_free_lines_count
        from tax_lines
        group by 1, 2
        order by year, abs(sum(gain_loss_eur)) desc, asset
        """
    ).fetchall()
    columns = [
        "asset",
        "year",
        "tax_lines_count",
        "proceeds_eur",
        "gain_loss_eur",
        "taxable_lines_count",
        "tax_free_lines_count",
    ]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def unmatched_disposal_summary(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        select
            date_part('year', event_time)::integer as year,
            upper(asset) as asset,
            source,
            count(*) as unmatched_count,
            sum(missing_quantity) as missing_quantity,
            sum(proceeds_total_eur) as proceeds_total_eur
        from tax_unmatched_disposals
        group by 1, 2, 3
        order by year, asset, source
        """
    ).fetchall()
    columns = ["year", "asset", "source", "unmatched_count", "missing_quantity", "proceeds_total_eur"]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def review_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("acquisition_raw_object_id") is None:
        reasons.append("acquisition_raw_missing")
    if row.get("disposal_raw_object_id") is None:
        reasons.append("disposal_raw_missing")
    if row.get("acquisition_price_eur") is None:
        reasons.append("acquisition_price_missing")
    if row.get("disposal_price_eur") is None:
        reasons.append("disposal_price_missing")
    if not row.get("acquisition_same_day_primary"):
        reasons.append("acquisition_same_day_primary_missing")
    if not row.get("disposal_same_day_primary"):
        reasons.append("disposal_same_day_primary_missing")
    if is_derived(row.get("acquisition_price_source")):
        reasons.append("acquisition_derived_price")
    if is_derived(row.get("disposal_price_source")):
        reasons.append("disposal_derived_price")
    if stale_days(row.get("acquisition_priced_at"), row.get("acquired_at")) > 7:
        reasons.append("acquisition_stale_price")
    if stale_days(row.get("disposal_priced_at"), row.get("disposed_at")) > 7:
        reasons.append("disposal_stale_price")
    gain_loss = decimal_value(row.get("gain_loss_eur"))
    proceeds = decimal_value(row.get("disposal_proceeds_eur"))
    if proceeds and abs(gain_loss / proceeds * Decimal("100")) >= Decimal("50"):
        reasons.append("large_gain_loss_ratio")
    if row.get("acquisition_source") and row.get("disposal_source") and row["acquisition_source"] != row["disposal_source"]:
        reasons.append("cross_source_fifo")
    return reasons or ["evidence_path_present"]


def is_derived(source: Any) -> bool:
    return str(source or "").lower().startswith("derived:")


def stale_days(price_time: Any, event_time: Any) -> int:
    if not isinstance(price_time, datetime) or not isinstance(event_time, datetime):
        return 0
    return max((event_time.date() - price_time.date()).days, 0)


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def write_top_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tax_line_id",
        "asset",
        "disposed_at",
        "quantity",
        "acquisition_cost_eur",
        "disposal_proceeds_eur",
        "gain_loss_eur",
        "holding_days",
        "acquired_at",
        "acquisition_source",
        "disposal_source",
        "acquisition_price_asset",
        "disposal_price_asset",
        "acquisition_price_source",
        "disposal_price_source",
        "acquisition_same_day_primary",
        "disposal_same_day_primary",
        "review_reasons",
        "acquisition_event_id",
        "disposal_event_id",
        "lot_id",
        "disposal_tx_id",
        "asset_fifo_drilldown_endpoint",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["review_reasons"] = ";".join(row.get("review_reasons", []))
            writer.writerow(csv_row)


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    main()
