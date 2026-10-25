#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

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

from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.pipeline import PipelineService  # noqa: E402

REPAIR_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_hnt_legacy_reward_price_repair_20260626.py"
PREVIEW_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_all_income_price_repair_preview_20260626.py"
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_PREVIEW = PROJECT_ROOT / "var" / "income_price_repair_previews" / "latest_all_income_price_repair_preview.json"
DEFAULT_V1_FX_DB = Path(str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db")))
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "income_price_repair_executes"
DEFAULT_PRICE_CACHE_DIR = PROJECT_ROOT / "var" / "external_price_history_cache"

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
    parser.add_argument("--price-cache-dir", default=str(DEFAULT_PRICE_CACHE_DIR))
    parser.add_argument("--refresh-price-cache", action="store_true")
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
                price_cache_dir=Path(args.price_cache_dir),
                refresh_price_cache=args.refresh_price_cache,
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
            "External CMC history is cached locally by provider/id/date range to make successful "
            "provider reads reproducible across later rate limits. "
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
    price_cache_dir: Path,
    refresh_price_cache: bool,
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
            cache_dir=price_cache_dir,
            refresh=refresh_price_cache,
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
                client=client,
                coin_id=str(row["coin_id"]),
                cmc_id=cmc_id,
                cmc_history=cmc_history,
                price_cache_dir=price_cache_dir,
                refresh_price_cache=refresh_price_cache,
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
    client: httpx.Client,
    coin_id: str,
    cmc_id: str | None,
    cmc_history: dict[date, Decimal],
    price_cache_dir: Path,
    refresh_price_cache: bool,
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
    defillama = fetch_defillama_cached_eur_price(
        client=client,
        coin_id=coin_id,
        price_date=price_date,
        v1_fx_db_path=v1_fx_db_path,
        source_label=source_label,
        cache_dir=price_cache_dir,
        refresh=refresh_price_cache,
    )
    if defillama is not None:
        return defillama
    raise ValueError(f"missing stable/cache/CMC/DefiLlama price for {asset} on {price_date.isoformat()}")


def fetch_coinmarketcap_usd_history(
    *,
    client: httpx.Client,
    cmc_id: str,
    start_date: date,
    end_date: date,
    cache_dir: Path = DEFAULT_PRICE_CACHE_DIR,
    refresh: bool = False,
) -> dict[date, Decimal]:
    cache_path = coinmarketcap_cache_path(
        cache_dir=cache_dir,
        cmc_id=cmc_id,
        start_date=start_date,
        end_date=end_date,
    )
    if cache_path.exists() and not refresh:
        return coinmarketcap_history_from_payload(json.loads(cache_path.read_text(encoding="utf-8")))
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
        if cache_path.exists():
            return coinmarketcap_history_from_payload(json.loads(cache_path.read_text(encoding="utf-8")))
        return {}
    response.raise_for_status()
    payload = response.json()
    if coinmarketcap_history_from_payload(payload):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return coinmarketcap_history_from_payload(payload)


def coinmarketcap_cache_path(*, cache_dir: Path, cmc_id: str, start_date: date, end_date: date) -> Path:
    return (
        cache_dir
        / "coinmarketcap_public_historical"
        / str(cmc_id)
        / f"{start_date.isoformat()}_{end_date.isoformat()}.json"
    )


def fetch_defillama_cached_eur_price(
    *,
    client: httpx.Client,
    coin_id: str,
    price_date: date,
    v1_fx_db_path: Path,
    source_label: str,
    cache_dir: Path = DEFAULT_PRICE_CACHE_DIR,
    refresh: bool = False,
) -> Any | None:
    cache_path = defillama_cache_path(cache_dir=cache_dir, coin_id=coin_id, price_date=price_date)
    payload: dict[str, Any] | None = None
    if cache_path.exists() and not refresh:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        timestamp = int(datetime.combine(price_date, time.min, tzinfo=UTC).timestamp())
        token_id = f"coingecko:{coin_id}"
        response = client.get(
            f"{REPAIR.DEFILLAMA_BASE_URL}/prices/historical/{timestamp}/{token_id}",
            headers={"accept": "application/json"},
        )
        if response.status_code in {401, 403, 404, 429}:
            if cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            else:
                return None
        else:
            response.raise_for_status()
            payload = response.json()
            if parse_defillama_usd_payload(payload, coin_id=coin_id)[0] > 0:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if payload is None:
        return None
    price_usd, provider_timestamp = parse_defillama_usd_payload(payload, coin_id=coin_id)
    if price_usd <= 0:
        return None
    usd_eur = REPAIR.usd_eur_rate(v1_fx_db_path, price_date)
    if usd_eur <= 0:
        return None
    return REPAIR.ExternalPrice(
        price_date=price_date,
        price_usd=price_usd,
        usd_eur=usd_eur,
        price_eur=price_usd * usd_eur,
        provider_timestamp=provider_timestamp,
        source=f"{source_label}:defillama_coingecko_history:{coin_id}",
    )


def parse_defillama_usd_payload(payload: dict[str, Any], *, coin_id: str) -> tuple[Decimal, int | None]:
    token_id = f"coingecko:{coin_id}"
    coin = payload.get("coins", {}).get(token_id) if isinstance(payload, dict) else None
    if not isinstance(coin, dict):
        return Decimal("0"), None
    provider_timestamp = coin.get("timestamp")
    return (
        decimal_value(coin.get("price")),
        int(provider_timestamp) if provider_timestamp is not None else None,
    )


def defillama_cache_path(*, cache_dir: Path, coin_id: str, price_date: date) -> Path:
    safe_coin_id = coin_id.replace("/", "_").replace(":", "_")
    return (
        cache_dir
        / "defillama_coingecko_historical"
        / safe_coin_id
        / f"{price_date.isoformat()}.json"
    )


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
