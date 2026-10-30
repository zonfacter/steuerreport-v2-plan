#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.contracts.prices import PricePointCreate  # noqa: E402
from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_V1_FX_DB = Path(str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db")))
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "hnt_legacy_reward_price_repairs"
SOURCE_LABEL = "defillama_coingecko_history:usd_eur:v1_fx_cache:hnt_legacy_reward_repair_20260626"
DEFILLAMA_BASE_URL = "https://coins.llama.fi"
COINMARKETCAP_HISTORICAL_URL = "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/historical"
STABLE_USD_ASSETS = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"}


@dataclass(frozen=True)
class RewardDay:
    price_date: date
    event_count: int
    quantity: Decimal
    current_income_eur: Decimal
    current_price_sources: tuple[str, ...]


@dataclass(frozen=True)
class ExternalPrice:
    price_date: date
    price_usd: Decimal
    usd_eur: Decimal
    price_eur: Decimal
    provider_timestamp: int | None
    source: str


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preview candidate Legacy-HNT reward prices; --execute is blocked until "
            "price, FX, identity and evidence contracts are verified."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--v1-fx-db", default=str(DEFAULT_V1_FX_DB))
    parser.add_argument("--year", type=int, default=2021)
    parser.add_argument("--asset", default="HNT")
    parser.add_argument("--source", default="helium")
    parser.add_argument("--coin-id", default="helium")
    parser.add_argument("--cmc-id", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--exclude-v1-asset-usd", action="store_true", help="V1-Asset/USD-Cache im Dry-run ausschliessen")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    if args.execute:
        raise SystemExit("--execute gesperrt: Preis-, FX-, Identitaets- und Belegvertrag sind nicht geprueft. Dry-run liefert nur Kandidaten.")

    db_path = Path(args.db)
    store = DuckDbStore(db_path)
    source_label = repair_source_label(asset=args.asset, source=args.source, year=args.year)
    reward_days = load_reward_days(
        store=store,
        year=args.year,
        asset=args.asset,
        source=args.source,
    )
    existing_primary_dates = load_primary_price_dates(
        store=store,
        year=args.year,
        asset=args.asset,
    )

    external_prices: dict[date, ExternalPrice] = {}
    failures: list[dict[str, Any]] = []
    with httpx.Client(timeout=args.timeout_seconds, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
        for reward_day in reward_days:
            if reward_day.price_date in existing_primary_dates:
                continue
            try:
                external_prices[reward_day.price_date] = fetch_defillama_eur_price(
                    client=client,
                    asset=args.asset,
                    coin_id=args.coin_id,
                    cmc_id=args.cmc_id,
                    price_date=reward_day.price_date,
                    v1_fx_db_path=Path(args.v1_fx_db),
                    source_label=source_label,
                    allow_v1_asset_usd=not args.exclude_v1_asset_usd,
                )
            except Exception as exc:  # noqa: BLE001 - CLI must expose provider/fx failures.
                failures.append({"date": reward_day.price_date.isoformat(), "error": str(exc)})

    report = build_report(
        mode="dry-run",
        year=args.year,
        asset=args.asset.upper(),
        source=args.source,
        reward_days=reward_days,
        external_prices=external_prices,
        existing_primary_dates=existing_primary_dates,
        failures=failures,
    )
    report["v1_asset_usd_excluded"] = args.exclude_v1_asset_usd

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_{args.year}_{args.asset.upper()}_legacy_reward_price_repair.json"
    latest_path = output_dir / f"latest_{args.year}_{args.asset.upper()}_legacy_reward_price_repair.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output_path": str(output_path), "latest_path": str(latest_path), **report}, indent=2))


def load_reward_days(*, store: DuckDbStore, year: int, asset: str, source: str) -> list[RewardDay]:
    lookup = HistoricalPriceLookup(store)
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    with store.connect() as con:
        rows = con.execute(
            """
            select event_time, quantity
            from canonical_events
            where upper(asset) = ?
              and lower(source) = ?
              and event_type in ('income', 'reward', 'staking', 'mining')
              and event_time >= ?
              and event_time < ?
            order by event_time
            """,
            [asset.upper(), source.lower(), start, end],
        ).fetchall()

    grouped: dict[date, dict[str, Any]] = {}
    for event_time, quantity in rows:
        event_time = ensure_utc(event_time)
        event_date = event_time.date()
        price = lookup.at_or_before(asset, event_time)
        price_eur = price.price_eur if price is not None else Decimal("0")
        bucket = grouped.setdefault(
            event_date,
            {
                "event_count": 0,
                "quantity": Decimal("0"),
                "current_income_eur": Decimal("0"),
                "sources": set(),
            },
        )
        qty = decimal_value(quantity)
        bucket["event_count"] += 1
        bucket["quantity"] += qty
        bucket["current_income_eur"] += abs(qty) * price_eur
        if price is not None:
            bucket["sources"].add(price.source)

    return [
        RewardDay(
            price_date=price_date,
            event_count=int(values["event_count"]),
            quantity=values["quantity"],
            current_income_eur=values["current_income_eur"],
            current_price_sources=tuple(sorted(values["sources"])),
        )
        for price_date, values in sorted(grouped.items())
    ]


def load_primary_price_dates(*, store: DuckDbStore, year: int, asset: str) -> set[date]:
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    with store.connect() as con:
        rows = con.execute(
            """
            select distinct cast(priced_at as date)
            from price_ledger
            where upper(asset) = ?
              and priced_at >= ?
              and priced_at < ?
              and not lower(source) like 'derived:%'
            """,
            [asset.upper(), start, end],
        ).fetchall()
    return {row[0] for row in rows}


def fetch_defillama_eur_price(
    *,
    client: httpx.Client,
    asset: str | None = None,
    coin_id: str,
    cmc_id: str | None = None,
    price_date: date,
    v1_fx_db_path: Path,
    source_label: str = SOURCE_LABEL,
    allow_v1_asset_usd: bool = True,
) -> ExternalPrice:
    if asset:
        stable = fetch_stablecoin_eur_price(
            asset=asset,
            price_date=price_date,
            v1_fx_db_path=v1_fx_db_path,
            source_label=source_label,
        )
        if stable is not None:
            return stable
        if allow_v1_asset_usd:
            cached = fetch_cached_eur_price(
                asset=asset,
                price_date=price_date,
                v1_fx_db_path=v1_fx_db_path,
                source_label=source_label,
            )
            if cached is not None:
                return cached
    if cmc_id:
        cmc = fetch_coinmarketcap_eur_price(
            cmc_id=cmc_id,
            price_date=price_date,
            v1_fx_db_path=v1_fx_db_path,
            source_label=source_label,
        )
        if cmc is not None:
            return cmc
    timestamp = int(datetime.combine(price_date, time.min, tzinfo=UTC).timestamp())
    token_id = f"coingecko:{coin_id}"
    response = client.get(
        f"{DEFILLAMA_BASE_URL}/prices/historical/{timestamp}/{token_id}",
        headers={"accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    coin = payload.get("coins", {}).get(token_id)
    if not isinstance(coin, dict):
        raise ValueError(f"missing DefiLlama coin payload for {token_id} on {price_date.isoformat()}")
    price_usd = decimal_value(coin.get("price"))
    if price_usd <= 0:
        raise ValueError(f"missing positive DefiLlama USD price for {token_id} on {price_date.isoformat()}")
    usd_eur = usd_eur_rate(v1_fx_db_path, price_date)
    if usd_eur <= 0:
        raise ValueError(f"missing USD/EUR FX rate for {price_date.isoformat()}")
    return ExternalPrice(
        price_date=price_date,
        price_usd=price_usd,
        usd_eur=usd_eur,
        price_eur=price_usd * usd_eur,
        provider_timestamp=int(coin["timestamp"]) if coin.get("timestamp") is not None else None,
        source=source_label,
    )


def fetch_stablecoin_eur_price(
    *,
    asset: str,
    price_date: date,
    v1_fx_db_path: Path,
    source_label: str,
) -> ExternalPrice | None:
    if asset.upper() not in STABLE_USD_ASSETS:
        return None
    usd_eur = usd_eur_rate(v1_fx_db_path, price_date)
    if usd_eur <= 0:
        return None
    return ExternalPrice(
        price_date=price_date,
        price_usd=Decimal("1"),
        usd_eur=usd_eur,
        price_eur=usd_eur,
        provider_timestamp=None,
        source=f"{source_label}:stable_usd_fx",
    )


def fetch_cached_eur_price(
    *,
    asset: str,
    price_date: date,
    v1_fx_db_path: Path,
    source_label: str,
) -> ExternalPrice | None:
    price_usd = asset_usd_rate(v1_fx_db_path, asset.upper(), price_date)
    if price_usd <= 0:
        return None
    usd_eur = usd_eur_rate(v1_fx_db_path, price_date)
    if usd_eur <= 0:
        return None
    return ExternalPrice(
        price_date=price_date,
        price_usd=price_usd,
        usd_eur=usd_eur,
        price_eur=price_usd * usd_eur,
        provider_timestamp=None,
        source=f"{source_label}:asset_usd_v1_fx_cache",
    )


def asset_usd_rate(db_path: Path, asset: str, rate_date: date) -> Decimal:
    if not db_path.exists():
        return Decimal("0")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        row = con.execute(
            """
            select rate
            from fx_cache
            where rate_date = ? and upper(base_ccy) = ? and quote_ccy = 'USD'
            order by updated_at_utc desc
            limit 1
            """,
            (rate_date.isoformat(), asset.upper()),
        ).fetchone()
    if row is None:
        return Decimal("0")
    return decimal_value(row[0])


def fetch_coinmarketcap_eur_price(
    *,
    cmc_id: str,
    price_date: date,
    v1_fx_db_path: Path,
    source_label: str,
) -> ExternalPrice | None:
    price_usd = coinmarketcap_usd_price(cmc_id=cmc_id, price_date=price_date)
    if price_usd <= 0:
        return None
    usd_eur = usd_eur_rate(v1_fx_db_path, price_date)
    if usd_eur <= 0:
        return None
    return ExternalPrice(
        price_date=price_date,
        price_usd=price_usd,
        usd_eur=usd_eur,
        price_eur=price_usd * usd_eur,
        provider_timestamp=None,
        source=f"{source_label}:coinmarketcap_public_historical:{cmc_id}",
    )


def coinmarketcap_usd_price(*, cmc_id: str, price_date: date) -> Decimal:
    import requests

    start_dt = datetime.combine(price_date, time.min, tzinfo=UTC)
    end_dt = start_dt + timedelta(days=1)
    response = requests.get(
        COINMARKETCAP_HISTORICAL_URL,
        params={
            "id": cmc_id,
            "convertId": "2781",
            "timeStart": int(start_dt.timestamp()),
            "timeEnd": int(end_dt.timestamp()),
        },
        headers={"accept": "application/json", "user-agent": "steuerreport-v2/0.1"},
        timeout=30,
    )
    if response.status_code in {401, 403, 404, 429}:
        return Decimal("0")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    quotes = data.get("quotes") if isinstance(data, dict) else None
    if not isinstance(quotes, list):
        return Decimal("0")
    for item in quotes:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote")
        if not isinstance(quote, dict):
            continue
        close = decimal_value(quote.get("close"))
        if close > 0:
            return close
    return Decimal("0")


def repair_source_label(*, asset: str, source: str, year: int) -> str:
    normalized_asset = asset.upper().strip()
    normalized_source = source.lower().strip().replace(":", "_")
    return (
        "defillama_coingecko_history:usd_eur:v1_fx_cache:"
        f"income_price_repair_20260626:{year}:{normalized_asset}:{normalized_source}"
    )


def usd_eur_rate(db_path: Path, rate_date: date) -> Decimal:
    if not db_path.exists():
        return Decimal("0")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        row = con.execute(
            """
            select rate
            from fx_cache
            where rate_date <= ? and base_ccy = 'USD' and quote_ccy = 'EUR'
            order by rate_date desc
            limit 1
            """,
            (rate_date.isoformat(),),
        ).fetchone()
    if row is None:
        return Decimal("0")
    return decimal_value(row[0])


def build_price_points(
    *,
    asset: str,
    reward_days: list[RewardDay],
    external_prices: dict[date, ExternalPrice],
    existing_primary_dates: set[date],
) -> list[PricePointCreate]:
    points: list[PricePointCreate] = []
    for reward_day in reward_days:
        if reward_day.price_date in existing_primary_dates:
            continue
        external = external_prices.get(reward_day.price_date)
        if external is None or is_unverified_v1_asset_usd(external):
            continue
        points.append(
            PricePointCreate(
                asset=asset.upper(),
                price_eur=external.price_eur,
                priced_at=datetime.combine(reward_day.price_date, time.min, tzinfo=UTC),
                source=external.source,
                confidence=Decimal("0.95"),
            )
        )
    return points


def is_unverified_v1_asset_usd(price: ExternalPrice) -> bool:
    return price.source.endswith(":asset_usd_v1_fx_cache")


def build_report(
    *,
    mode: str,
    year: int,
    asset: str,
    source: str,
    reward_days: list[RewardDay],
    external_prices: dict[date, ExternalPrice],
    existing_primary_dates: set[date],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    current_total = Decimal("0")
    repaired_total = Decimal("0")
    importable = 0
    unverified_v1 = 0
    existing_primary = 0
    for reward_day in reward_days:
        external = external_prices.get(reward_day.price_date)
        repaired_income = (
            abs(reward_day.quantity) * external.price_eur if external is not None else Decimal("0")
        )
        current_total += reward_day.current_income_eur
        repaired_total += repaired_income
        has_primary = reward_day.price_date in existing_primary_dates
        unverified = external is not None and is_unverified_v1_asset_usd(external)
        if has_primary:
            existing_primary += 1
        elif unverified:
            unverified_v1 += 1
        elif external is not None:
            importable += 1
        rows.append(
            {
                "date": reward_day.price_date.isoformat(),
                "event_count": reward_day.event_count,
                "quantity": str(reward_day.quantity),
                "current_income_eur": str(reward_day.current_income_eur),
                "current_avg_eur": str(safe_div(reward_day.current_income_eur, abs(reward_day.quantity))),
                "current_price_sources": list(reward_day.current_price_sources),
                "external_price_usd": str(external.price_usd) if external else None,
                "usd_eur": str(external.usd_eur) if external else None,
                "external_price_eur": str(external.price_eur) if external else None,
                "repaired_income_eur": str(repaired_income),
                "delta_eur": str(repaired_income - reward_day.current_income_eur),
                "existing_primary_price": has_primary,
                "will_import": False,
                "v1_asset_usd_unverified": unverified,
                "provider_timestamp": external.provider_timestamp if external else None,
                "source": external.source if external else None,
            }
        )
    return {
        "mode": mode,
        "execute_allowed": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "year": year,
        "asset": asset,
        "source": source,
        "methodology": (
            "Dry-run results are unapproved candidates and may create reports or initialise the store. "
            "V1 asset/USD candidates lack verified identity, timing, evidence and snapshot and cannot "
            "be imported. --execute is blocked even when the V1 asset cache is excluded. Other sources "
            "and FX remain unverified; excluding the cache is not an evidence or tax approval. "
            "The legacy importable_price_days count describes candidates, not permission to import."
        ),
        "summary": {
            "reward_days": len(reward_days),
            "event_count": sum(day.event_count for day in reward_days),
            "quantity": str(sum((day.quantity for day in reward_days), Decimal("0"))),
            "current_income_eur": str(current_total),
            "repaired_income_eur": str(repaired_total),
            "delta_eur": str(repaired_total - current_total),
            "external_price_days": len(external_prices),
            "existing_primary_days": existing_primary,
            "importable_price_days": importable,
            "unverified_v1_asset_usd_days": unverified_v1,
            "failure_count": len(failures),
        },
        "failures": failures,
        "rows": rows,
    }


def backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_hnt_legacy_reward_price_repair_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


if __name__ == "__main__":
    main()
