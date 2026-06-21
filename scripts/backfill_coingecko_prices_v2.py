#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService

COINGECKO_SOURCE = "coingecko:coins-history"
COINGECKO_CURRENT_SOURCE = "coingecko:simple-price"

ASSET_IDS = {
    "AVAX": "avalanche-2",
    "BONK": "bonk",
    "ETHW": "ethereum-pow-iou",
    "LINK": "chainlink",
    "MOBILE": "helium-mobile",
    "TRX": "tron",
    "XLM": "stellar",
    "XRP": "ripple",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing V2 EUR prices from CoinGecko historical coin data."
    )
    parser.add_argument("--db", default="data/steuerreport_v2.duckdb")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--assets", nargs="*", default=None)
    parser.add_argument("--sleep-seconds", type=float, default=8.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--allow-current-fallback", action="store_true")
    args = parser.parse_args()

    store = DuckDbStore(args.db)
    targets = _missing_portfolio_targets(store)
    if args.assets:
        requested = {asset.upper() for asset in args.assets}
        targets = [target for target in targets if target["asset"] in requested]

    results: list[dict[str, Any]] = []
    price_points: list[PricePointCreate] = []
    for index, target in enumerate(targets):
        asset = target["asset"]
        coin_id = ASSET_IDS.get(asset)
        result: dict[str, Any] = {**target, "coin_id": coin_id}
        if coin_id is None:
            result["status"] = "missing_coin_id"
            results.append(result)
            continue
        if index > 0:
            time.sleep(args.sleep_seconds)
        try:
            price_eur, priced_at, source = _fetch_price_eur(
                coin_id=coin_id,
                event_time=target["priced_at"],
                timeout=args.timeout_seconds,
                allow_current_fallback=args.allow_current_fallback,
            )
        except Exception as exc:  # noqa: BLE001 - CLI reports provider errors verbatim.
            result["status"] = "error"
            result["error"] = str(exc)
            results.append(result)
            continue
        if price_eur is None:
            result["status"] = "missing_eur_price"
            results.append(result)
            continue
        result["status"] = "ready"
        result["price_eur"] = str(price_eur)
        result["price_source"] = source
        result["price_at"] = priced_at
        results.append(result)
        price_points.append(
            PricePointCreate(
                asset=asset,
                price_eur=price_eur,
                priced_at=priced_at,
                source=source,
                confidence=Decimal("0.90"),
            )
        )

    pipeline = None
    if args.execute and price_points:
        store.add_price_points(price_points)
        pipeline = PipelineService(store).rebuild_all().model_dump(mode="json")

    print(
        json.dumps(
            {
                "mode": "execute" if args.execute else "dry-run",
                "targets": _json_ready(results),
                "created": len(price_points) if args.execute else 0,
                "ready": len(price_points),
                "pipeline": pipeline,
            },
            indent=2,
        )
    )


def _missing_portfolio_targets(store: DuckDbStore) -> list[dict[str, Any]]:
    with store.connect() as con:
        rows = con.execute(
            """
            with positions as (
                select account, asset, sum(delta_quantity) as quantity
                from balance_ledger
                group by account, asset
                having abs(sum(delta_quantity)) > 0.00000001
            ),
            priced as (
                select distinct asset from price_ledger
            )
            select
                p.account,
                p.asset,
                p.quantity,
                max(e.event_time) as priced_at
            from positions p
            left join priced pr on pr.asset = p.asset
            left join canonical_events e
                on e.account = p.account
                and (e.asset = p.asset or e.quote_asset = p.asset or e.fee_asset = p.asset)
            where pr.asset is null and p.asset <> 'EUR'
            group by p.account, p.asset, p.quantity
            order by abs(p.quantity) desc, p.asset
            """
        ).fetchall()
    return [
        {
            "account": row[0],
            "asset": row[1],
            "quantity": row[2],
            "priced_at": _ensure_utc(row[3]),
        }
        for row in rows
    ]


def _fetch_price_eur(
    *,
    coin_id: str,
    event_time: datetime,
    timeout: float,
    allow_current_fallback: bool,
) -> tuple[Decimal | None, datetime, str]:
    try:
        return (
            _fetch_history_price_eur(
                coin_id=coin_id,
                event_time=event_time,
                timeout=timeout,
            ),
            event_time,
            COINGECKO_SOURCE,
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if not allow_current_fallback or status not in {401, 403, 404, 429}:
            raise
        current_price = _fetch_current_price_eur(coin_id=coin_id, timeout=timeout)
        return current_price, datetime.now(timezone.utc), COINGECKO_CURRENT_SOURCE


def _fetch_history_price_eur(
    *,
    coin_id: str,
    event_time: datetime,
    timeout: float,
) -> Decimal | None:
    response = requests.get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/history",
        params={"date": event_time.strftime("%d-%m-%Y"), "localization": "false"},
        timeout=timeout,
        headers={"accept": "application/json"},
    )
    if response.status_code == 429:
        response.raise_for_status()
    response.raise_for_status()
    payload = response.json()
    price = payload.get("market_data", {}).get("current_price", {}).get("eur")
    if price is None:
        return None
    return Decimal(str(price))


def _fetch_current_price_eur(*, coin_id: str, timeout: float) -> Decimal | None:
    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": coin_id, "vs_currencies": "eur"},
        timeout=timeout,
        headers={"accept": "application/json"},
    )
    response.raise_for_status()
    price = response.json().get(coin_id, {}).get("eur")
    if price is None:
        return None
    return Decimal(str(price))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    main()
