from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.contracts.prices import (
    CurrentPortfolioPriceBackfillJob,
    CurrentPortfolioPriceBackfillResult,
    ExternalPriceBackfillJob,
    ExternalPriceBackfillResult,
    PricePointCreate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
DEFILLAMA_COINS_BASE_URL = "https://coins.llama.fi"
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"
DEFAULT_CONFIG = Path("/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json")
EXAMPLE_CONFIG = Path("/workspace/steuerreport/configs/crypto_price_sources.example.json")


@dataclass(frozen=True)
class _PriceAsset:
    symbol: str
    coingecko_id: str | None
    aliases: tuple[str, ...]
    defillama_id: str | None = None


class ExternalPriceBackfillService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def run(
        self,
        *,
        config_path: str,
        v1_fx_db_path: str,
        provider: str,
        assets_filter: list[str],
        max_requests: int,
        timeout_seconds: int,
        confidence: Decimal,
        dry_run: bool,
    ) -> ExternalPriceBackfillResult:
        assets = self._load_assets(config_path)
        alias_map = self._alias_map(assets)
        requirements = PriceCoverageService(self.store).requirements().requirements
        jobs: list[ExternalPriceBackfillJob] = []
        prices: list[PricePointCreate] = []
        attempted = 0
        skipped = 0
        failed = 0
        max_requests = max(0, min(max_requests, 1000))
        timeout_seconds = max(3, min(timeout_seconds, 60))
        requested_assets = sorted({asset.strip().upper() for asset in assets_filter if asset.strip()})
        seen_asset_dates: set[tuple[str, str]] = set()

        with httpx.Client(timeout=timeout_seconds, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
            for requirement in requirements:
                if requested_assets and requirement.asset.upper() not in requested_assets:
                    continue
                asset_date_key = (requirement.asset.upper(), requirement.price_date.isoformat())
                if asset_date_key in seen_asset_dates:
                    continue
                seen_asset_dates.add(asset_date_key)
                if attempted >= max_requests:
                    break
                asset = alias_map.get(requirement.asset.upper())
                if asset is None:
                    skipped += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            status="skipped",
                            reason="asset_not_configured",
                        )
                    )
                    continue
                usd_eur = self._usd_eur_rate(v1_fx_db_path, requirement.price_date.isoformat())
                if usd_eur <= 0:
                    skipped += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            provider_id=asset.coingecko_id or asset.defillama_id,
                            status="skipped",
                            reason="usd_eur_missing",
                        )
                    )
                    continue
                if dry_run:
                    attempted += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            provider_id=asset.coingecko_id or asset.defillama_id,
                            status="planned",
                            usd_eur=usd_eur,
                        )
                    )
                    continue

                attempted += 1
                fetch_kwargs: dict[str, object] = {
                    "client": client,
                    "coingecko_id": asset.coingecko_id,
                    "date_str": requirement.price_date.isoformat(),
                    "provider": provider,
                }
                if asset.defillama_id:
                    fetch_kwargs["defillama_id"] = asset.defillama_id
                price_usd, source = self._fetch_price_usd(**fetch_kwargs)
                price_source_date = requirement.price_date.isoformat()
                if price_usd <= 0:
                    price_usd, source, price_source_date = self._fetch_first_available_price_usd_after(
                        client=client,
                        coingecko_id=asset.coingecko_id,
                        defillama_id=asset.defillama_id,
                        date_str=requirement.price_date.isoformat(),
                        provider=provider,
                    )
                    if price_usd > 0:
                        usd_eur = self._usd_eur_rate(v1_fx_db_path, price_source_date)
                        source = f"{source}:first_available_after:{price_source_date}"
                        if usd_eur <= 0:
                            skipped += 1
                            jobs.append(
                                ExternalPriceBackfillJob(
                                    asset=requirement.asset,
                                    price_date=requirement.price_date,
                                    provider_id=asset.coingecko_id or asset.defillama_id,
                                    status="skipped",
                                    reason="usd_eur_missing",
                                )
                            )
                            continue
                if price_usd <= 0:
                    failed += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            provider_id=asset.coingecko_id or asset.defillama_id,
                            status="failed",
                            reason="asset_usd_missing",
                        )
                    )
                    continue
                price_eur = price_usd * usd_eur
                source_label = f"{source}:usd_eur:v1_fx_cache:{price_source_date}"
                prices.append(
                    PricePointCreate(
                        asset=requirement.asset,
                        price_eur=price_eur,
                        priced_at=datetime.combine(
                            requirement.price_date,
                            datetime.min.time(),
                            tzinfo=timezone.utc,
                        ),
                        source=source_label,
                        confidence=confidence,
                    )
                )
                jobs.append(
                    ExternalPriceBackfillJob(
                        asset=requirement.asset,
                        price_date=requirement.price_date,
                        provider_id=asset.coingecko_id,
                        status="imported",
                        price_usd=price_usd,
                        usd_eur=usd_eur,
                        price_eur=price_eur,
                        source=source_label,
                    )
                )

        pipeline = None
        if prices:
            self.store.add_price_points(prices)
            pipeline = PipelineService(self.store).rebuild_all()
        return ExternalPriceBackfillResult(
            requirements_count=len(requirements),
            configured_assets=sorted({asset.symbol for asset in assets}),
            asset_filter=requested_assets,
            planned_jobs=sum(1 for job in jobs if job.status in {"planned", "imported"}),
            attempted=attempted,
            imported_prices=len(prices),
            skipped=skipped,
            failed=failed,
            dry_run=dry_run,
            jobs=jobs[:200],
            pipeline=pipeline,
        )

    def run_current_portfolio(
        self,
        *,
        config_path: str,
        provider: str,
        assets_filter: list[str],
        max_requests: int,
        timeout_seconds: int,
        confidence: Decimal,
        dry_run: bool,
    ) -> CurrentPortfolioPriceBackfillResult:
        assets = self._load_assets(config_path)
        alias_map = self._alias_map(assets)
        portfolio_assets = sorted(
            {
                position.asset.upper()
                for position in BalanceLedgerBuilder(self.store).positions()
                if position.quantity > 0 and position.asset.upper() != "EUR"
            }
        )
        requested_assets = sorted(
            {asset.strip().upper() for asset in assets_filter if asset.strip()}
        )
        selected_assets = [
            asset
            for asset in portfolio_assets
            if not requested_assets or asset in requested_assets
        ][: max(0, min(max_requests, 250))]
        jobs: list[CurrentPortfolioPriceBackfillJob] = []
        prices: list[PricePointCreate] = []
        skipped = 0
        failed = 0
        attempted = 0
        priced_at = datetime.now(timezone.utc)
        timeout_seconds = max(3, min(timeout_seconds, 60))
        normalized_provider = provider if provider in {"coingecko"} else "coingecko"

        configured: dict[str, _PriceAsset] = {}
        for asset_symbol in selected_assets:
            asset = alias_map.get(asset_symbol)
            if asset is None:
                skipped += 1
                jobs.append(
                    CurrentPortfolioPriceBackfillJob(
                        asset=asset_symbol,
                        status="skipped",
                        reason="asset_not_configured",
                    )
                )
                continue
            configured[asset_symbol] = asset

        coingecko_prices: dict[str, Decimal] = {}
        defillama_prices_usd: dict[str, Decimal] = {}
        usd_eur = Decimal("0")
        fx_source_date = ""
        if configured and not dry_run:
            with httpx.Client(
                timeout=timeout_seconds,
                headers={"user-agent": "steuerreport-v2/0.1"},
            ) as client:
                coingecko_prices = self._fetch_coingecko_simple_prices_eur(
                    client,
                    sorted(
                        {
                            asset.coingecko_id
                            for asset in configured.values()
                            if asset.coingecko_id
                        }
                    ),
                )
                defillama_prices_usd = self._fetch_defillama_current_prices_usd(
                    client,
                    sorted(
                        {
                            asset.defillama_id
                            for asset in configured.values()
                            if asset.defillama_id
                        }
                    ),
                )
                if defillama_prices_usd:
                    usd_eur, fx_source_date = self._fetch_frankfurter_usd_eur(client)

        for asset_symbol, asset in configured.items():
            attempted += 1
            provider_id = asset.defillama_id or asset.coingecko_id
            source_label = (
                "defillama_token_current:usd_eur:frankfurter_latest"
                if asset.defillama_id
                else f"{normalized_provider}:simple-price:eur"
            )
            if dry_run:
                jobs.append(
                    CurrentPortfolioPriceBackfillJob(
                        asset=asset_symbol,
                        provider_id=provider_id,
                        status="planned",
                        source=source_label,
                    )
                )
                continue
            price_eur = Decimal("0")
            if asset.defillama_id and usd_eur > 0:
                price_usd = defillama_prices_usd.get(asset.defillama_id, Decimal("0"))
                if price_usd > 0:
                    price_eur = price_usd * usd_eur
                    source_label = (
                        "defillama_token_current:usd_eur:"
                        f"frankfurter_latest:{fx_source_date}"
                    )
            if price_eur <= 0 and asset.coingecko_id:
                price_eur = coingecko_prices.get(asset.coingecko_id, Decimal("0"))
                source_label = f"{normalized_provider}:simple-price:eur"
            if price_eur <= 0:
                failed += 1
                jobs.append(
                    CurrentPortfolioPriceBackfillJob(
                        asset=asset_symbol,
                        provider_id=provider_id,
                        status="failed",
                        reason="asset_eur_missing",
                        source=source_label,
                    )
                )
                continue
            prices.append(
                PricePointCreate(
                    asset=asset_symbol,
                    price_eur=price_eur,
                    priced_at=priced_at,
                    source=source_label,
                    confidence=confidence,
                )
            )
            jobs.append(
                CurrentPortfolioPriceBackfillJob(
                    asset=asset_symbol,
                    provider_id=provider_id,
                    status="imported",
                    price_eur=price_eur,
                    source=source_label,
                )
            )

        pipeline = None
        if prices:
            self.store.add_price_points(prices)
            pipeline = PipelineService(self.store).rebuild_all()
        return CurrentPortfolioPriceBackfillResult(
            portfolio_assets_count=len(portfolio_assets),
            configured_assets=sorted({asset.symbol for asset in assets}),
            asset_filter=requested_assets,
            planned_jobs=sum(1 for job in jobs if job.status in {"planned", "imported"}),
            attempted=attempted,
            imported_prices=len(prices),
            skipped=skipped,
            failed=failed,
            dry_run=dry_run,
            priced_at=priced_at,
            jobs=jobs[:250],
            pipeline=pipeline,
        )

    def _load_assets(self, config_path: str) -> list[_PriceAsset]:
        path = Path(config_path).expanduser()
        if not path.exists():
            path = EXAMPLE_CONFIG
        payload = json.loads(path.read_text(encoding="utf-8"))
        result: list[_PriceAsset] = []
        for item in payload.get("assets", []):
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper().strip()
            coingecko_id = str(item.get("coingecko_id", "")).strip() or None
            defillama_id = str(item.get("defillama_id", "")).strip() or None
            aliases = tuple(
                str(value).upper().strip()
                for value in [symbol, *item.get("aliases", []), *item.get("store_keys", [])]
                if str(value).strip()
            )
            if symbol and (coingecko_id or defillama_id) and aliases:
                result.append(
                    _PriceAsset(
                        symbol=symbol,
                        coingecko_id=coingecko_id,
                        aliases=aliases,
                        defillama_id=defillama_id,
                    )
                )
        return result

    def _alias_map(self, assets: list[_PriceAsset]) -> dict[str, _PriceAsset]:
        result: dict[str, _PriceAsset] = {}
        for asset in assets:
            result[asset.symbol] = asset
            for alias in asset.aliases:
                result[alias] = asset
        return result

    def _usd_eur_rate(self, db_path: str, rate_date: str) -> Decimal:
        path = Path(db_path).expanduser()
        if not path.exists():
            return Decimal("0")
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            row = con.execute(
                """
                select rate
                from fx_cache
                where rate_date <= ? and base_ccy = 'USD' and quote_ccy = 'EUR'
                order by rate_date desc
                limit 1
                """,
                (rate_date,),
            ).fetchone()
        if row is None:
            return Decimal("0")
        return self._decimal(row[0])

    def _fetch_price_usd(
        self,
        *,
        client: httpx.Client,
        coingecko_id: str | None,
        date_str: str,
        provider: str,
        defillama_id: str | None = None,
    ) -> tuple[Decimal, str]:
        normalized_provider = provider if provider in {"auto", "coingecko", "defillama"} else "auto"
        if normalized_provider != "defillama" and coingecko_id:
            price = self._fetch_coingecko_history_price(client, coingecko_id, date_str)
            if price > 0:
                return price, "coingecko_history"
        if normalized_provider != "coingecko":
            token_id = defillama_id or (f"coingecko:{coingecko_id}" if coingecko_id else "")
            if token_id:
                price = self._fetch_defillama_history_price(client, token_id, date_str)
                if price > 0:
                    return (
                        price,
                        "defillama_token_history"
                        if defillama_id
                        else "defillama_coingecko_history",
                    )
        return Decimal("0"), ""

    def _fetch_first_available_price_usd_after(
        self,
        *,
        client: httpx.Client,
        coingecko_id: str | None,
        defillama_id: str | None = None,
        date_str: str,
        provider: str,
        max_days_after: int = 7,
    ) -> tuple[Decimal, str, str]:
        start = datetime.strptime(date_str, "%Y-%m-%d")
        for offset in range(1, max_days_after + 1):
            candidate = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
            fetch_kwargs: dict[str, object] = {
                "client": client,
                "coingecko_id": coingecko_id,
                "date_str": candidate,
                "provider": provider,
            }
            if defillama_id:
                fetch_kwargs["defillama_id"] = defillama_id
            price, source = self._fetch_price_usd(**fetch_kwargs)
            if price > 0:
                return price, source, candidate
        return Decimal("0"), "", date_str

    def _fetch_coingecko_history_price(
        self,
        client: httpx.Client,
        coingecko_id: str,
        date_str: str,
    ) -> Decimal:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        response = client.get(
            f"{COINGECKO_BASE_URL}/coins/{coingecko_id}/history",
            params={"date": dt.strftime("%d-%m-%Y"), "localization": "false"},
        )
        if response.status_code in {401, 403, 404, 429} or response.status_code >= 500:
            return Decimal("0")
        response.raise_for_status()
        data = response.json()
        market_data = data.get("market_data") if isinstance(data, dict) else None
        current_price = market_data.get("current_price") if isinstance(market_data, dict) else None
        if not isinstance(current_price, dict):
            return Decimal("0")
        return self._decimal(current_price.get("usd"))

    def _fetch_defillama_history_price(
        self,
        client: httpx.Client,
        token_id: str,
        date_str: str,
    ) -> Decimal:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        timestamp = int(dt.replace(tzinfo=UTC).timestamp())
        response = client.get(
            f"{DEFILLAMA_COINS_BASE_URL}/prices/historical/{timestamp}/{token_id}",
            headers={"accept": "application/json"},
        )
        if response.status_code in {401, 403, 404, 429} or response.status_code >= 500:
            return Decimal("0")
        response.raise_for_status()
        data = response.json()
        coins = data.get("coins") if isinstance(data, dict) else None
        coin = coins.get(token_id) if isinstance(coins, dict) else None
        if not isinstance(coin, dict):
            return Decimal("0")
        return self._decimal(coin.get("price"))

    def _fetch_defillama_current_prices_usd(
        self,
        client: httpx.Client,
        token_ids: list[str],
    ) -> dict[str, Decimal]:
        if not token_ids:
            return {}
        response = client.get(
            f"{DEFILLAMA_COINS_BASE_URL}/prices/current/{','.join(token_ids)}",
            headers={"accept": "application/json"},
        )
        if response.status_code in {401, 403, 404, 429} or response.status_code >= 500:
            return {}
        response.raise_for_status()
        data = response.json()
        coins = data.get("coins") if isinstance(data, dict) else None
        if not isinstance(coins, dict):
            return {}
        result: dict[str, Decimal] = {}
        for token_id in token_ids:
            coin = coins.get(token_id)
            if not isinstance(coin, dict):
                continue
            price = self._decimal(coin.get("price"))
            if price > 0:
                result[token_id] = price
        return result

    def _fetch_frankfurter_usd_eur(
        self,
        client: httpx.Client,
    ) -> tuple[Decimal, str]:
        response = client.get(
            f"{FRANKFURTER_BASE_URL}/latest",
            params={"from": "USD", "to": "EUR"},
            headers={"accept": "application/json"},
        )
        if response.status_code in {401, 403, 404, 429} or response.status_code >= 500:
            return Decimal("0"), ""
        response.raise_for_status()
        data = response.json()
        rates = data.get("rates") if isinstance(data, dict) else None
        if not isinstance(rates, dict):
            return Decimal("0"), ""
        return self._decimal(rates.get("EUR")), str(data.get("date") or "")

    def _fetch_coingecko_simple_prices_eur(
        self,
        client: httpx.Client,
        coingecko_ids: list[str],
    ) -> dict[str, Decimal]:
        if not coingecko_ids:
            return {}
        response = client.get(
            f"{COINGECKO_BASE_URL}/simple/price",
            params={
                "ids": ",".join(coingecko_ids),
                "vs_currencies": "eur",
            },
        )
        if response.status_code in {401, 403, 404, 429} or response.status_code >= 500:
            return {}
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return {}
        result: dict[str, Decimal] = {}
        for coingecko_id in coingecko_ids:
            item = data.get(coingecko_id)
            if not isinstance(item, dict):
                continue
            price = self._decimal(item.get("eur"))
            if price > 0:
                result[coingecko_id] = price
        return result

    def _decimal(self, value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal("0")
