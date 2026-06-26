#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService

REPAIR_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_hnt_legacy_reward_price_repair_20260626.py"
PREVIEW_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_all_income_price_repair_preview_20260626.py"
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_PREVIEW = PROJECT_ROOT / "var" / "income_price_repair_previews" / "latest_all_income_price_repair_preview.json"
DEFAULT_V1_FX_DB = Path("/root/.local/share/steuerreport/steuerreport.db")
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "income_price_repair_executes"

REPAIR_SPEC = importlib.util.spec_from_file_location("income_price_repair", REPAIR_SCRIPT_PATH)
REPAIR = importlib.util.module_from_spec(REPAIR_SPEC)
assert REPAIR_SPEC.loader is not None
sys.modules[REPAIR_SPEC.name] = REPAIR
REPAIR_SPEC.loader.exec_module(REPAIR)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply all ready_for_execute groups from an all-income price repair preview in one rebuild."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--preview", default=str(DEFAULT_PREVIEW))
    parser.add_argument("--v1-fx-db", default=str(DEFAULT_V1_FX_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    db_path = Path(args.db)
    preview = json.loads(Path(args.preview).read_text(encoding="utf-8"))
    ready_rows = select_ready_rows(preview.get("rows", []))
    store = DuckDbStore(db_path)
    price_points = []
    group_reports: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    with httpx.Client(timeout=args.timeout_seconds, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
        for row in ready_rows:
            report, points = build_group_points(
                store=store,
                row=row,
                client=client,
                v1_fx_db_path=Path(args.v1_fx_db),
            )
            group_reports.append(report)
            if report["summary"]["failure_count"]:
                failures.append(
                    {
                        "asset": row["asset"],
                        "source": row["source"],
                        "year": row["year"],
                        "failure_count": report["summary"]["failure_count"],
                        "failures": report["failures"][:20],
                    }
                )
            price_points.extend(points)

    result: dict[str, Any] = {
        "mode": "execute" if args.execute else "dry-run",
        "generated_at": datetime.now(UTC).isoformat(),
        "preview_path": str(Path(args.preview)),
        "ready_groups": len(ready_rows),
        "created_price_points_planned": len(price_points),
        "failure_count": len(failures),
        "failures": failures,
        "groups": group_reports,
        "methodology": (
            "Applies only preview rows with status=ready_for_execute. Each group is recomputed "
            "before writing; execution aborts if any recomputed group has provider/fx failures. "
            "Existing price rows are not deleted. One DB backup and one PipelineService.rebuild_all "
            "are used for the whole batch."
        ),
    }

    if args.execute:
        if failures:
            raise SystemExit(f"aborting execute: {len(failures)} group(s) have recompute failures")
        backup_path = backup_database(db_path)
        created = store.add_price_points(price_points)
        pipeline = PipelineService(store).rebuild_all()
        result["execute"] = {
            "backup_path": str(backup_path),
            "created_price_points": len(created),
            "pipeline": pipeline.model_dump(mode="json"),
        }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_ready_income_price_repairs.json"
    latest_path = output_dir / "latest_ready_income_price_repairs.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output_path": str(output_path), "latest_path": str(latest_path), **result}, indent=2))


def select_ready_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("status") == "ready_for_execute"
        and row.get("asset")
        and row.get("source")
        and row.get("year") is not None
        and row.get("coin_id")
    ]


def build_group_points(
    *,
    store: DuckDbStore,
    row: dict[str, Any],
    client: httpx.Client,
    v1_fx_db_path: Path,
) -> tuple[dict[str, Any], list[Any]]:
    asset = str(row["asset"]).upper()
    source = str(row["source"]).lower()
    year = int(row["year"])
    reward_days = REPAIR.load_reward_days(
        store=store,
        year=year,
        asset=asset,
        source=source,
    )
    existing_primary_dates = REPAIR.load_primary_price_dates(
        store=store,
        year=year,
        asset=asset,
    )
    missing_dates = [
        reward_day.price_date
        for reward_day in reward_days
        if reward_day.price_date not in existing_primary_dates
    ]
    cmc_history: dict[date, Decimal] = {}
    cmc_id = str(row["cmc_id"]) if row.get("cmc_id") else None
    if cmc_id and missing_dates and asset.upper() not in REPAIR.STABLE_USD_ASSETS:
        cmc_history = fetch_coinmarketcap_usd_history(
            client=client,
            cmc_id=cmc_id,
            start_date=min(missing_dates),
            end_date=max(missing_dates),
        )
    external_prices = {}
    failures: list[dict[str, Any]] = []
    source_label = REPAIR.repair_source_label(asset=asset, source=source, year=year)
    for reward_day in reward_days:
        if reward_day.price_date in existing_primary_dates:
            continue
        try:
            external_prices[reward_day.price_date] = resolve_external_price(
                asset=asset,
                price_date=reward_day.price_date,
                v1_fx_db_path=v1_fx_db_path,
                source_label=source_label,
                cmc_id=cmc_id,
                cmc_history=cmc_history,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in report and aborts execute.
            failures.append({"date": reward_day.price_date.isoformat(), "error": str(exc)})
    report = REPAIR.build_report(
        mode="dry-run",
        year=year,
        asset=asset,
        source=source,
        reward_days=reward_days,
        external_prices=external_prices,
        existing_primary_dates=existing_primary_dates,
        failures=failures,
    )
    points = REPAIR.build_price_points(
        asset=asset,
        reward_days=reward_days,
        external_prices=external_prices,
        existing_primary_dates=existing_primary_dates,
    )
    return report, points


def resolve_external_price(
    *,
    asset: str,
    price_date: date,
    v1_fx_db_path: Path,
    source_label: str,
    cmc_id: str | None,
    cmc_history: dict[date, Decimal],
) -> Any:
    stable = REPAIR.fetch_stablecoin_eur_price(
        asset=asset,
        price_date=price_date,
        v1_fx_db_path=v1_fx_db_path,
        source_label=source_label,
    )
    if stable is not None:
        return stable
    cached = REPAIR.fetch_cached_eur_price(
        asset=asset,
        price_date=price_date,
        v1_fx_db_path=v1_fx_db_path,
        source_label=source_label,
    )
    if cached is not None:
        return cached
    if cmc_id:
        price_usd = cmc_history.get(price_date, Decimal("0"))
        if price_usd > 0:
            usd_eur = REPAIR.usd_eur_rate(v1_fx_db_path, price_date)
            if usd_eur <= 0:
                raise ValueError(f"missing USD/EUR FX rate for {price_date.isoformat()}")
            return REPAIR.ExternalPrice(
                price_date=price_date,
                price_usd=price_usd,
                usd_eur=usd_eur,
                price_eur=price_usd * usd_eur,
                provider_timestamp=None,
                source=f"{source_label}:coinmarketcap_public_historical:{cmc_id}",
            )
    raise ValueError(f"missing stable/cache/CMC price for {asset} on {price_date.isoformat()}")


def fetch_coinmarketcap_usd_history(
    *,
    client: httpx.Client,
    cmc_id: str,
    start_date: date,
    end_date: date,
) -> dict[date, Decimal]:
    response = client.get(
        REPAIR.COINMARKETCAP_HISTORICAL_URL,
        params={
            "id": cmc_id,
            "convertId": "2781",
            "timeStart": int(datetime.combine(start_date, time.min, tzinfo=UTC).timestamp()),
            "timeEnd": int(datetime.combine(end_date, time.min, tzinfo=UTC).timestamp()) + 86400,
        },
        headers={"accept": "application/json"},
    )
    if response.status_code in {401, 403, 404, 429}:
        return {}
    response.raise_for_status()
    return coinmarketcap_history_from_payload(response.json())


def coinmarketcap_history_from_payload(payload: dict[str, Any]) -> dict[date, Decimal]:
    data = payload.get("data") if isinstance(payload, dict) else None
    quotes = data.get("quotes") if isinstance(data, dict) else None
    if not isinstance(quotes, list):
        return {}
    result: dict[date, Decimal] = {}
    for item in quotes:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote")
        if not isinstance(quote, dict):
            continue
        close = decimal_value(quote.get("close"))
        if close <= 0:
            continue
        quote_date = quote_date_from_item(item)
        if quote_date is not None:
            result[quote_date] = close
    return result


def quote_date_from_item(item: dict[str, Any]) -> date | None:
    for key in ("timeOpen", "timestamp", "timeClose"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                normalized = value.replace("Z", "+00:00")
                return datetime.fromisoformat(normalized).astimezone(UTC).date()
            except ValueError:
                continue
    return None


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = db_path.parent / "backups" / f"{db_path.stem}_before_ready_income_price_repairs_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


if __name__ == "__main__":
    main()
