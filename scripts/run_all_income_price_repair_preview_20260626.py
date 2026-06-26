#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.db.duckdb_store import DuckDbStore

REPAIR_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_hnt_legacy_reward_price_repair_20260626.py"
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "crypto_price_sources.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "income_price_repair_previews"

SPEC = importlib.util.spec_from_file_location("income_price_repair", REPAIR_SCRIPT_PATH)
REPAIR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = REPAIR
SPEC.loader.exec_module(REPAIR)


@dataclass(frozen=True)
class CandidateGroup:
    asset: str
    source: str
    year: int
    day_count: int
    event_count: int
    quantity: Decimal
    missing_primary_days: int


@dataclass(frozen=True)
class PriceAssetConfig:
    coingecko_id: str
    coinmarketcap_id: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only all-asset preview for taxable income/reward/staking/mining "
            "groups whose event days lack primary historical EUR price anchors."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--v1-fx-db", default=str(REPAIR.DEFAULT_V1_FX_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--assets", nargs="*", default=None)
    parser.add_argument("--years", nargs="*", type=int, default=None)
    parser.add_argument("--sources", nargs="*", default=None)
    parser.add_argument("--max-groups", type=int, default=40)
    parser.add_argument("--max-external-days", type=int, default=1200)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    db_path = Path(args.db)
    config = load_price_config(Path(args.config))
    candidates = load_candidate_groups(
        db_path=db_path,
        assets=args.assets,
        years=args.years,
        sources=args.sources,
    )[: max(1, args.max_groups)]

    store = DuckDbStore(db_path)
    rows: list[dict[str, Any]] = []
    total_external_days = 0
    with httpx.Client(timeout=args.timeout_seconds, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
        for candidate in candidates:
            asset_config = config.get(candidate.asset)
            coin_id = asset_config.coingecko_id if asset_config is not None else None
            cmc_id = asset_config.coinmarketcap_id if asset_config is not None else None
            row = {
                "asset": candidate.asset,
                "source": candidate.source,
                "year": candidate.year,
                "coin_id": coin_id,
                "cmc_id": cmc_id,
                "day_count": candidate.day_count,
                "event_count": candidate.event_count,
                "quantity": str(candidate.quantity),
                "missing_primary_days": candidate.missing_primary_days,
            }
            if coin_id is None:
                row["status"] = "missing_coin_id"
                rows.append(row)
                continue
            if total_external_days >= args.max_external_days:
                row["status"] = "external_day_budget_exhausted"
                rows.append(row)
                continue
            reward_days = REPAIR.load_reward_days(
                store=store,
                year=candidate.year,
                asset=candidate.asset,
                source=candidate.source,
            )
            existing_primary_dates = REPAIR.load_primary_price_dates(
                store=store,
                year=candidate.year,
                asset=candidate.asset,
            )
            to_fetch = [
                reward_day
                for reward_day in reward_days
                if reward_day.price_date not in existing_primary_dates
            ]
            remaining_budget = args.max_external_days - total_external_days
            budget_limited = len(to_fetch) > remaining_budget
            external_prices = {}
            failures: list[dict[str, Any]] = []
            for reward_day in to_fetch[:remaining_budget]:
                try:
                    external_prices[reward_day.price_date] = REPAIR.fetch_defillama_eur_price(
                        client=client,
                        asset=candidate.asset,
                        coin_id=coin_id,
                        cmc_id=cmc_id,
                        price_date=reward_day.price_date,
                        v1_fx_db_path=Path(args.v1_fx_db),
                        source_label=REPAIR.repair_source_label(
                            asset=candidate.asset,
                            source=candidate.source,
                            year=candidate.year,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - report provider gaps per group.
                    failures.append({"date": reward_day.price_date.isoformat(), "error": str(exc)})
            total_external_days += len(to_fetch[:remaining_budget])
            report = REPAIR.build_report(
                mode="dry-run",
                year=candidate.year,
                asset=candidate.asset,
                source=candidate.source,
                reward_days=reward_days,
                external_prices=external_prices,
                existing_primary_dates=existing_primary_dates,
                failures=failures,
            )
            summary = report["summary"]
            row.update(
                {
                    "status": "external_day_budget_exhausted" if budget_limited else group_status(summary),
                    "current_income_eur": summary["current_income_eur"],
                    "preview_income_eur": None if budget_limited else summary["repaired_income_eur"],
                    "delta_eur": None if budget_limited else summary["delta_eur"],
                    "external_price_days": summary["external_price_days"],
                    "existing_primary_days": summary["existing_primary_days"],
                    "importable_price_days": summary["importable_price_days"],
                    "failure_count": summary["failure_count"],
                    "budget_limited": budget_limited,
                    "failures": failures[:20],
                }
            )
            rows.append(row)

    report = {
        "mode": "dry-run",
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": (
            "Read-only all-asset scan of taxable income/reward/staking/mining event days. "
            "Groups are selected when at least one event day has no non-derived same-day "
            "price anchor. External previews prefer stable-USD FX pricing, local V1 asset/USD "
            "and USD/EUR cache values, CoinMarketCap public historical closes, and then "
            "DefiLlama CoinGecko history. No price_ledger, FIFO or import data is changed."
        ),
        "summary": {
            "candidate_groups": len(candidates),
            "configured_groups": sum(1 for row in rows if row.get("coin_id")),
            "missing_coin_id_groups": sum(1 for row in rows if row.get("status") == "missing_coin_id"),
            "ready_groups": sum(1 for row in rows if row.get("status") == "ready_for_execute"),
            "review_groups": sum(1 for row in rows if row.get("status") != "ready_for_execute"),
            "external_days_attempted": total_external_days,
            "total_delta_eur": str(
                sum((decimal_value(row.get("delta_eur")) for row in rows), Decimal("0"))
            ),
        },
        "rows": rows,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_all_income_price_repair_preview.json"
    latest_path = output_dir / "latest_all_income_price_repair_preview.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output_path": str(output_path), "latest_path": str(latest_path), **report}, indent=2))


def load_coin_ids(path: Path) -> dict[str, str]:
    return {
        key: item.coingecko_id
        for key, item in load_price_config(path).items()
    }


def load_price_config(path: Path) -> dict[str, PriceAssetConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, PriceAssetConfig] = {}
    for item in payload.get("assets", []):
        symbol = str(item.get("symbol", "")).upper().strip()
        coin_id = str(item.get("coingecko_id", "")).strip()
        cmc_id_raw = str(item.get("coinmarketcap_id", "")).strip()
        asset_config = PriceAssetConfig(
            coingecko_id=coin_id,
            coinmarketcap_id=cmc_id_raw or None,
        )
        if symbol and coin_id:
            result[symbol] = asset_config
            for value in [*item.get("aliases", []), *item.get("store_keys", [])]:
                alias = str(value).upper().strip()
                if alias:
                    result[alias] = asset_config
    return result


def load_candidate_groups(
    *,
    db_path: Path,
    assets: list[str] | None,
    years: list[int] | None,
    sources: list[str] | None,
) -> list[CandidateGroup]:
    asset_filter = sorted({item.upper() for item in assets or []})
    source_filter = sorted({item.lower() for item in sources or []})
    year_filter = sorted(set(years or []))
    with duckdb.connect(str(db_path), read_only=True) as con:
        rows = con.execute(
            """
            with event_days as (
                select
                    upper(asset) as asset,
                    lower(source) as event_source,
                    date_part('year', event_time)::integer as tax_year,
                    cast(event_time as date) as price_date,
                    count(*) as event_count,
                    sum(abs(quantity)) as quantity
                from canonical_events
                where event_type in ('income', 'reward', 'staking', 'mining')
                  and upper(asset) <> 'EUR'
                  and (? = [] or upper(asset) in (select unnest(?)))
                  and (? = [] or date_part('year', event_time)::integer in (select unnest(?)))
                  and (? = [] or lower(source) in (select unnest(?)))
                group by 1,2,3,4
            ),
            primary_days as (
                select upper(asset) as asset, cast(priced_at as date) as price_date
                from price_ledger
                where not lower(source) like 'derived:%'
                group by 1,2
            )
            select
                event_days.asset,
                event_days.event_source,
                event_days.tax_year,
                count(*) as day_count,
                sum(event_days.event_count) as event_count,
                sum(event_days.quantity) as quantity,
                sum(case when primary_days.asset is null then 1 else 0 end) as missing_primary_days
            from event_days
            left join primary_days
              on primary_days.asset = event_days.asset
             and primary_days.price_date = event_days.price_date
            group by 1,2,3
            having missing_primary_days > 0
            order by missing_primary_days desc, event_count desc, asset, tax_year, event_source
            """,
            [asset_filter, asset_filter, year_filter, year_filter, source_filter, source_filter],
        ).fetchall()
    return [
        CandidateGroup(
            asset=row[0],
            source=row[1],
            year=int(row[2]),
            day_count=int(row[3]),
            event_count=int(row[4]),
            quantity=decimal_value(row[5]),
            missing_primary_days=int(row[6]),
        )
        for row in rows
    ]


def group_status(summary: dict[str, Any]) -> str:
    if int(summary["failure_count"]):
        return "provider_or_fx_review_required"
    if int(summary["importable_price_days"]):
        return "ready_for_execute"
    return "no_import_needed"


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:  # noqa: BLE001 - CLI JSON summary fallback.
        return Decimal("0")


if __name__ == "__main__":
    main()
