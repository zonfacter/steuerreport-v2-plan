from __future__ import annotations

import json
import hashlib
import logging
import sqlite3
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from steuerreport_v2.domain.external_http import managed_client

from steuerreport_v2.contracts.prices import (
    CurrentPortfolioPriceBackfillJob,
    CurrentPortfolioPriceBackfillResult,
    CurrentPortfolioPriceBackfillStatus,
    ExternalPriceBackfillJob,
    ExternalPriceBackfillResult,
    ExternalPriceBackfillStatus,
    PriceBackfillCheckpoint,
    PricePointCreate,
)
from steuerreport_v2.contracts.common import ApiMessage
from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.domain.historical_fx import FxReference, cache_fx_reference, select_fx_reference
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder
from steuerreport_v2.paths import PROJECT_ROOT, resolve_project_path

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
DEFILLAMA_COINS_BASE_URL = "https://coins.llama.fi"
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"
FX_REFERENCE_INVALID = "usd_eur_source_date_or_source_invalid"
FX_REFERENCE_UNVERIFIED = "usd_eur_daily_reference_unverified"
PRICE_CANDIDATE_OUT_OF_RANGE = "price_candidate_out_of_range"
PRICE_OUT_OF_RANGE = "price_out_of_range"
FX_SOURCE_UNREADABLE = "usd_eur_source_unreadable"
PRICE_PROVIDER_ERROR = "price_provider_error"
FX_REFERENCE_INVALID_MESSAGE = (
    "USD/EUR-Referenz nicht verwendet: Quelltag, Quelllabel oder Waehrungseinheit fehlen "
    "oder sind ungueltig; der Quelltag muss innerhalb von sieben Tagen vor dem Bewertungstag liegen. "
    "Auch eine zulaessige Tagesreferenz ist nur zeitlich begrenzt und ohne geprueften Originalbeleg; "
    "eine intrataegliche Kurs- oder Veroeffentlichungszeit wurde nicht geprueft."
)
FX_REFERENCE_UNVERIFIED_MESSAGE = (
    "Die USD/EUR-Tagesreferenz besteht nur die begrenzte technische Datumspruefung. "
    "Originalbeleg, Veroeffentlichungszeit und intrataegliche Kurszeit sind nicht geprueft; "
    "dies ist keine fachliche Freigabe."
)
DEFAULT_CONFIG = PROJECT_ROOT / "configs/crypto_price_sources.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "configs/crypto_price_sources.example.json"
logger = logging.getLogger(__name__)


class HistoricalBackfillIncompleteError(RuntimeError):
    """A backfill did not complete; callers must stop and inspect state."""


class HistoricalBackfillStorageUnknown(HistoricalBackfillIncompleteError):
    def __init__(self, warnings: list[ApiMessage] | None = None) -> None:
        super().__init__("Preisbackfill: Speicherzustand unbekannt; vor Wiederholung pruefen.")
        self.warnings = list(warnings or [])


class HistoricalBackfillPipelineFailed(HistoricalBackfillIncompleteError):
    def __init__(self, stored_price_ids: list[str] | None = None) -> None:
        super().__init__("Preisbackfill: Pipeline fehlgeschlagen; Folgen unbekannt oder teilweise.")
        self.stored_price_ids = list(stored_price_ids or [])


class HistoricalBackfillJobsFailed(HistoricalBackfillIncompleteError):
    def __init__(self, stored_price_ids: list[str] | None = None) -> None:
        super().__init__("Preisbackfill: Preisjobs fehlgeschlagen; Ergebnisse vor Fortsetzung pruefen.")
        self.stored_price_ids = list(stored_price_ids or [])


class CurrentBackfillReplayBlocked(RuntimeError):
    pass


class CurrentBackfillReservationUnknown(RuntimeError):
    pass


class CurrentBackfillProviderContextFailed(RuntimeError):
    pass


class CurrentBackfillStorageUnknown(RuntimeError):
    def __init__(self, warnings: list[ApiMessage]) -> None:
        super().__init__("Aktueller Preisbackfill: Speicherzustand unbekannt.")
        self.warnings = warnings


class HistoricalBackfillReplayBlocked(HistoricalBackfillIncompleteError):
    pass


class HistoricalBackfillReservationUnknown(HistoricalBackfillIncompleteError):
    pass


class CurrentBackfillStatusUnknown(RuntimeError):
    pass


class HistoricalBackfillStatusUnknown(HistoricalBackfillIncompleteError):
    pass


class HistoricalBackfillJournalUnknown(HistoricalBackfillIncompleteError):
    def __init__(self, stored_price_ids: list[str] | None = None) -> None:
        super().__init__("Historisches Auftragsergebnis nicht sicher dokumentiert; vor Fortsetzung pruefen.")
        self.stored_price_ids = list(stored_price_ids or [])


class CurrentBackfillPipelineInterrupted(RuntimeError):
    def __init__(self, stored_price_ids: list[str]) -> None:
        super().__init__("Pipeline unterbrochen; Preise gespeichert, Pipelinefolgen unklar.")
        self.stored_price_ids = list(stored_price_ids)


class HistoricalBackfillPipelineInterrupted(HistoricalBackfillIncompleteError):
    def __init__(self, stored_price_ids: list[str]) -> None:
        super().__init__("Historische Pipeline unterbrochen; Preise gespeichert, Pipelinefolgen unklar.")
        self.stored_price_ids = list(stored_price_ids)


class CurrentBackfillPipelineStartUnknown(RuntimeError):
    def __init__(self, stored_price_ids: list[str]) -> None:
        super().__init__("Pipelinebeginn unklar; Preise gespeichert, Zustand vor Fortsetzung pruefen.")
        self.stored_price_ids = list(stored_price_ids)


class HistoricalBackfillPipelineStartUnknown(HistoricalBackfillIncompleteError):
    def __init__(self, stored_price_ids: list[str]) -> None:
        super().__init__("Historischer Pipelinebeginn unklar; Preise gespeichert, Zustand vor Fortsetzung pruefen.")
        self.stored_price_ids = list(stored_price_ids)


@contextmanager
def _current_price_client(timeout: int):
    try:
        with managed_client(timeout=timeout, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
            yield client
    except RequestCancelled:
        raise RequestCancelled("request_cancelled") from None
    except RequestDeadlineExceeded:
        raise RequestDeadlineExceeded("request_deadline_exceeded") from None
    except Exception:
        logger.error("Current portfolio price provider context failed")
        raise CurrentBackfillProviderContextFailed("Preisprovider nicht verfuegbar; keine Preise gespeichert.") from None


def require_backfill_pipeline_success(result: ExternalPriceBackfillResult) -> None:
    if result.pipeline_status == "failed":
        raise HistoricalBackfillPipelineFailed(result.stored_price_ids)
    if result.failed:
        raise HistoricalBackfillJobsFailed(result.stored_price_ids)
    if getattr(result, "result_journal_status", "not_started") == "unknown":
        raise HistoricalBackfillJournalUnknown(result.stored_price_ids)


def fx_reference_warnings(jobs: list) -> list[ApiMessage]:
    warnings = []
    if any(job.reason == FX_REFERENCE_INVALID for job in jobs):
        warnings.append(ApiMessage(code=FX_REFERENCE_INVALID, message=FX_REFERENCE_INVALID_MESSAGE))
    if any(job.reason == FX_REFERENCE_UNVERIFIED for job in jobs):
        warnings.append(ApiMessage(code=FX_REFERENCE_UNVERIFIED, message=FX_REFERENCE_UNVERIFIED_MESSAGE))
    if any(job.reason == FX_SOURCE_UNREADABLE for job in jobs):
        warnings.append(ApiMessage(code=FX_SOURCE_UNREADABLE, message="Die FX-Quelle konnte nicht gelesen werden."))
    if any(job.reason == PRICE_PROVIDER_ERROR or PRICE_PROVIDER_ERROR in getattr(job, "additional_reasons", []) for job in jobs):
        warnings.append(ApiMessage(code=PRICE_PROVIDER_ERROR, message="Ein Preisabruf ist fehlgeschlagen."))
    if any(job.reason == PRICE_CANDIDATE_OUT_OF_RANGE for job in jobs):
        warnings.append(ApiMessage(code=PRICE_CANDIDATE_OUT_OF_RANGE, message=(
            "Ein nicht darstellbarer Preiskandidat wurde verworfen; ein anderer Kurs wurde verwendet. "
            "Die Quelle und Bewertung bleiben zu pruefen."
        )))
    if any(job.reason == PRICE_OUT_OF_RANGE or PRICE_OUT_OF_RANGE in getattr(job, "additional_reasons", [])
           for job in jobs):
        warnings.append(ApiMessage(code=PRICE_OUT_OF_RANGE, message=(
            "Ein EUR-Preiskandidat liegt ausserhalb des speicherbaren Bereichs "
            "und wurde nicht gespeichert."
        )))
    return warnings


def backfill_result_warnings(result: Any) -> list[ApiMessage]:
    warnings = fx_reference_warnings(result.jobs)
    if result.failed:
        warnings.append(ApiMessage(code="price_backfill_partial_failure", message=(
            f"{result.failed} Preisjobs sind fehlgeschlagen; bereits gespeicherte Preise "
            "bleiben bestehen. Einzelne Ergebnisse vor einem erneuten Abruf pruefen."
        )))
    return warnings


def checked_eur_price(price_usd: Decimal, usd_eur: Decimal, *, preserve_exact_scale: bool = False) -> Decimal | None:
    """Return only positive values representable by the price ledger's DECIMAL(38,18)."""
    if not price_usd.is_finite() or not usd_eur.is_finite() or price_usd <= 0 or usd_eur <= 0:
        return None
    digits = len(price_usd.as_tuple().digits) + len(usd_eur.as_tuple().digits)
    if digits > 256:
        return None
    try:
        with localcontext() as arithmetic:
            arithmetic.prec = max(60, digits + 20)
            product = price_usd * usd_eur
            value = product.quantize(Decimal("0.000000000000000001"))
    except DecimalException:
        return None
    if not value.is_finite() or value <= 0 or value >= Decimal("1e20"):
        return None
    if preserve_exact_scale and product == value and product.as_tuple().exponent >= -18:
        return product
    return value


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
        request_id: str | None = None,
    ) -> ExternalPriceBackfillResult:
        request_hash = None
        if not dry_run:
            request_hash = self._reserve_historical_backfill(
                request_id=request_id, config_path=config_path, v1_fx_db_path=v1_fx_db_path,
                provider=provider, assets_filter=assets_filter, max_requests=max_requests,
                timeout_seconds=timeout_seconds, confidence=confidence,
            )
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
        token_risk_statuses = self._token_risk_statuses()

        with managed_client(timeout=timeout_seconds, headers={"user-agent": "steuerreport-v2/0.1"}) as client:
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
                if token_risk_statuses.get(requirement.asset.upper()) == "spam_review":
                    skipped += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            provider_id=asset.coingecko_id or asset.defillama_id,
                            status="skipped",
                            reason="token_risk_spam_review",
                        )
                    )
                    continue
                try:
                    fx_reference = self._timed_usd_eur_reference(v1_fx_db_path, requirement.price_date.isoformat())
                except (sqlite3.DatabaseError, OSError):
                    logger.error("Historical price backfill FX source could not be read")
                    failed += 1
                    jobs.append(ExternalPriceBackfillJob(
                        asset=requirement.asset, price_date=requirement.price_date,
                        provider_id=asset.coingecko_id or asset.defillama_id,
                        status="failed", reason=FX_SOURCE_UNREADABLE,
                    ))
                    continue
                if fx_reference is None:
                    skipped += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            provider_id=asset.coingecko_id or asset.defillama_id,
                            status="skipped",
                            reason=FX_REFERENCE_INVALID,
                        )
                    )
                    continue
                usd_eur = fx_reference.rate_eur_per_usd
                if dry_run:
                    attempted += 1
                    jobs.append(
                        ExternalPriceBackfillJob(
                            asset=requirement.asset,
                            price_date=requirement.price_date,
                            provider_id=asset.coingecko_id or asset.defillama_id,
                            status="planned",
                            reason=FX_REFERENCE_UNVERIFIED,
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
                try:
                    price_usd, source = self._fetch_price_usd(**fetch_kwargs)
                except (RequestCancelled, RequestDeadlineExceeded):
                    raise
                except Exception:
                    logger.error("Historical price backfill provider request failed")
                    failed += 1
                    jobs.append(ExternalPriceBackfillJob(
                        asset=requirement.asset, price_date=requirement.price_date,
                        provider_id=asset.coingecko_id or asset.defillama_id,
                        status="failed", reason=PRICE_PROVIDER_ERROR,
                    ))
                    continue
                price_source_date = requirement.price_date.isoformat()
                # A later first quote is not evidence for this historical event day.
                if not price_usd.is_finite() or price_usd <= 0:
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
                price_eur = checked_eur_price(price_usd, usd_eur)
                if price_eur is None:
                    failed += 1
                    jobs.append(ExternalPriceBackfillJob(
                        asset=requirement.asset, price_date=requirement.price_date,
                        provider_id=asset.coingecko_id or asset.defillama_id,
                        status="failed", reason="price_out_of_range",
                    ))
                    continue
                source_label = f"{source}:usd_eur:v1_fx_cache:{price_source_date}:{fx_reference.source_suffix()}"
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
                        reason=FX_REFERENCE_UNVERIFIED,
                        price_usd=price_usd,
                        usd_eur=usd_eur,
                        price_eur=price_eur,
                        source=source_label,
                    )
                )

        pipeline = None
        stored_price_ids: list[str] = []
        pipeline_status = "not_started"
        pipeline_effects = "not_started"
        if request_hash is not None:
            try:
                stored_price_ids = self._prepare_prices(request_hash, "historical", prices)
            except Exception:
                logger.error("Historical price backfill storage failed; storage state unknown")
                stored_price_ids = None
            if stored_price_ids is None:
                warnings = fx_reference_warnings(jobs)
                if failed:
                    warnings.append(ApiMessage(code="price_backfill_partial_failure", message=(
                        f"{failed} Preisjobs sind vor dem Speicherfehler fehlgeschlagen."
                    )))
                raise HistoricalBackfillStorageUnknown(warnings)
        if stored_price_ids:
            pipeline, pipeline_status, pipeline_effects = self._pipeline_after_prepare(
                request_hash, "historical", stored_price_ids,
            )
        visible_jobs = jobs[:200]
        tracked_reasons = (FX_REFERENCE_INVALID, FX_REFERENCE_UNVERIFIED, PRICE_OUT_OF_RANGE,
                           FX_SOURCE_UNREADABLE, PRICE_PROVIDER_ERROR)
        for reason in tracked_reasons:
            if any(job.reason == reason for job in jobs) and not any(job.reason == reason for job in visible_jobs):
                counts = Counter(job.reason for job in visible_jobs)
                replace_at = next(i for i in range(len(visible_jobs) - 1, -1, -1)
                                  if visible_jobs[i].reason not in tracked_reasons
                                  or counts[visible_jobs[i].reason] > 1)
                visible_jobs[replace_at] = next(job for job in jobs if job.reason == reason)
        result = ExternalPriceBackfillResult(
            requirements_count=len(requirements),
            configured_assets=sorted({asset.symbol for asset in assets}),
            asset_filter=requested_assets,
            planned_jobs=sum(1 for job in jobs if job.status in {"planned", "imported"}),
            attempted=attempted,
            imported_prices=len(prices),
            skipped=skipped,
            failed=failed,
            dry_run=dry_run,
            jobs=visible_jobs,
            pipeline=pipeline,
            stored_price_ids=stored_price_ids,
            pipeline_status=pipeline_status,
            pipeline_effects=pipeline_effects,
        )
        if request_hash is not None:
            result.result_journal_status = "recorded"
            try:
                self.store.record_historical_price_backfill(request_hash, result.model_dump_json())
            except (RequestCancelled, RequestDeadlineExceeded):
                raise HistoricalBackfillPipelineInterrupted(stored_price_ids) from None
            except Exception:
                logger.error("Historical price result journal failed")
                result.result_journal_status = "unknown"
        return result

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
        request_id: str | None = None,
    ) -> CurrentPortfolioPriceBackfillResult:
        request_hash = None
        if not dry_run:
            request_hash = self._reserve_current_backfill(
                request_id=request_id, config_path=config_path, provider=provider,
                assets_filter=assets_filter, max_requests=max_requests,
                timeout_seconds=timeout_seconds, confidence=confidence,
            )
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
        token_risk_statuses = self._token_risk_statuses()

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
            if token_risk_statuses.get(asset_symbol) == "spam_review":
                skipped += 1
                jobs.append(
                    CurrentPortfolioPriceBackfillJob(
                        asset=asset_symbol,
                        provider_id=asset.defillama_id or asset.coingecko_id,
                        status="skipped",
                        reason="token_risk_spam_review",
                    )
                )
                continue
            configured[asset_symbol] = asset

        coingecko_prices: dict[str, Decimal] = {}
        defillama_prices_usd: dict[str, Decimal] = {}
        usd_eur = Decimal("0")
        fx_source_date = ""
        fx_reference = None
        coingecko_failed = defillama_failed = fx_failed = False
        if configured and not dry_run:
            with _current_price_client(timeout_seconds) as client:
                coingecko_ids = sorted({asset.coingecko_id for asset in configured.values() if asset.coingecko_id})
                defillama_ids = sorted({asset.defillama_id for asset in configured.values() if asset.defillama_id})
                if coingecko_ids:
                    try:
                        coingecko_prices = self._fetch_coingecko_simple_prices_eur(client, coingecko_ids)
                    except RequestCancelled:
                        raise RequestCancelled("request_cancelled") from None
                    except RequestDeadlineExceeded:
                        raise RequestDeadlineExceeded("request_deadline_exceeded") from None
                    except Exception:
                        logger.error("Current portfolio price provider request failed")
                        coingecko_failed = True
                if defillama_ids:
                    try:
                        defillama_prices_usd = self._fetch_defillama_current_prices_usd(client, defillama_ids)
                    except RequestCancelled:
                        raise RequestCancelled("request_cancelled") from None
                    except RequestDeadlineExceeded:
                        raise RequestDeadlineExceeded("request_deadline_exceeded") from None
                    except Exception:
                        logger.error("Current portfolio price provider request failed")
                        defillama_failed = True
                if defillama_prices_usd:
                    try:
                        usd_eur, fx_source_date = self._fetch_frankfurter_usd_eur(client)
                        fx_reference = select_fx_reference(
                            [{"base": "USD", "quote": "EUR", "rate": usd_eur, "date": fx_source_date}]
                            if fx_source_date < priced_at.date().isoformat() else [],
                            priced_at.date(),
                        )
                    except RequestCancelled:
                        raise RequestCancelled("request_cancelled") from None
                    except RequestDeadlineExceeded:
                        raise RequestDeadlineExceeded("request_deadline_exceeded") from None
                    except Exception:
                        logger.error("Current portfolio FX provider request failed")
                        fx_failed = True

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
            price_usd = defillama_prices_usd.get(asset.defillama_id, Decimal("0")) if asset.defillama_id else Decimal("0")
            fx_rejected = bool(price_usd.is_finite() and price_usd > 0 and fx_reference is None)
            used_fx = False
            price_out_of_range = False
            provider_error = bool((asset.coingecko_id and coingecko_failed) or
                                  (asset.defillama_id and (defillama_failed or
                                   (fx_failed and price_usd.is_finite() and price_usd > 0))))
            if asset.defillama_id and fx_reference is not None:
                if price_usd.is_finite() and price_usd > 0:
                    converted = checked_eur_price(price_usd, usd_eur, preserve_exact_scale=True)
                    price_out_of_range = converted is None
                    price_eur = converted or Decimal("0")
                    source_label = (
                        "defillama_token_current:usd_eur:"
                        f"frankfurter_latest:{fx_source_date}"
                    )
                    used_fx = True
            if price_eur <= 0 and asset.coingecko_id:
                direct = coingecko_prices.get(asset.coingecko_id, Decimal("0"))
                if direct.is_finite() and direct > 0:
                    provider_id = asset.coingecko_id
                    source_label = f"{normalized_provider}:simple-price:eur"
                converted = checked_eur_price(direct, Decimal("1"), preserve_exact_scale=True)
                price_out_of_range = price_out_of_range or (direct.is_finite() and direct > 0 and converted is None)
                price_eur = converted or Decimal("0")
                if price_eur > 0:
                    provider_id = asset.coingecko_id
                    source_label = f"{normalized_provider}:simple-price:eur"
                    used_fx = False
            if price_eur <= 0:
                failed += 1
                jobs.append(
                    CurrentPortfolioPriceBackfillJob(
                        asset=asset_symbol,
                        provider_id=provider_id,
                        status="failed",
                        reason=FX_REFERENCE_INVALID if fx_rejected else ("price_out_of_range" if price_out_of_range else PRICE_PROVIDER_ERROR if provider_error else "asset_eur_missing"),
                        additional_reasons=([PRICE_OUT_OF_RANGE] if fx_rejected and price_out_of_range else []) + ([PRICE_PROVIDER_ERROR] if provider_error else []),
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
                    reason=(FX_REFERENCE_INVALID if fx_rejected else
                            PRICE_CANDIDATE_OUT_OF_RANGE if price_out_of_range else
                            FX_REFERENCE_UNVERIFIED if used_fx else None),
                    additional_reasons=[PRICE_PROVIDER_ERROR] if provider_error else [],
                    price_eur=price_eur,
                    source=source_label,
                )
            )

        pipeline = None
        stored_price_ids: list[str] | None = []
        pipeline_status = "not_started"
        pipeline_effects = "not_started"
        if request_hash is not None:
            try:
                stored_price_ids = self._prepare_prices(request_hash, "current_portfolio", prices)
            except Exception:
                logger.error("Current portfolio price storage failed; storage state unknown")
                stored_price_ids = None
            if stored_price_ids is None:
                warnings = fx_reference_warnings(jobs)
                if failed:
                    warnings.append(ApiMessage(code="price_backfill_partial_failure", message=f"{failed} Preisjobs sind vor dem Speicherfehler fehlgeschlagen."))
                raise CurrentBackfillStorageUnknown(warnings)
        if stored_price_ids:
            pipeline, pipeline_status, pipeline_effects = self._pipeline_after_prepare(
                request_hash, "current_portfolio", stored_price_ids,
            )
        result = CurrentPortfolioPriceBackfillResult(
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
            stored_price_ids=stored_price_ids,
            pipeline_status=pipeline_status,
            pipeline_effects=pipeline_effects,
        )
        if request_hash is not None:
            result.result_journal_status = "recorded"
            try:
                self.store.record_current_price_backfill(request_hash, result.model_dump_json())
            except (RequestCancelled, RequestDeadlineExceeded):
                raise CurrentBackfillPipelineInterrupted(stored_price_ids) from None
            except Exception:
                logger.error("Current portfolio price result journal failed")
                result.result_journal_status = "unknown"
        return result

    @staticmethod
    def _explicit_current_request_hash(request_id: str) -> str:
        return hashlib.sha256(json.dumps(
            {"request_id": request_id}, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    def current_portfolio_request_status(self, request_id: str) -> CurrentPortfolioPriceBackfillStatus:
        return self._request_status(self._explicit_current_request_hash(request_id), "current_portfolio")

    @staticmethod
    def _explicit_historical_request_hash(request_id: str) -> str:
        return hashlib.sha256(json.dumps(
            {"operation_kind": "historical", "request_id": str(UUID(str(request_id)))},
            sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

    def historical_request_status(self, request_id: str) -> ExternalPriceBackfillStatus:
        try:
            key = self._explicit_historical_request_hash(request_id)
        except (ValueError, TypeError, AttributeError):
            raise HistoricalBackfillStatusUnknown("Historischer Auftragsstatus nicht sicher lesbar.") from None
        return self._request_status(key, "historical")

    def _request_status(self, request_hash: str, operation_kind: str):
        status_model = (CurrentPortfolioPriceBackfillStatus if operation_kind == "current_portfolio"
                        else ExternalPriceBackfillStatus)
        result_model = (CurrentPortfolioPriceBackfillResult if operation_kind == "current_portfolio"
                        else ExternalPriceBackfillResult)
        error = CurrentBackfillStatusUnknown if operation_kind == "current_portfolio" else HistoricalBackfillStatusUnknown
        try:
            with self.store.read_snapshot() as snapshot:
                row = snapshot.price_backfill_operation_record(request_hash, operation_kind)
                if row is None:
                    return status_model(status="not_found", explanation=(
                        "Kein Auftrag zu dieser Kennung gespeichert; kein Ausfuehrungsnachweis."
                    ))
                if not isinstance(row, tuple) or len(row) != 2:
                    raise ValueError("operation_record_invalid")
                result_json, checkpoint_json = row
                checkpoint = None
                checkpoint_sha256 = None
                if checkpoint_json is not None:
                    payload = self._stored_object(checkpoint_json)
                    if set(payload) != set(PriceBackfillCheckpoint.model_fields):
                        raise ValueError("checkpoint_fields_invalid")
                    checkpoint = PriceBackfillCheckpoint.model_validate(payload)
                    if checkpoint.operation_kind != operation_kind:
                        raise ValueError("checkpoint_operation_mismatch")
                    checkpoint_sha256 = hashlib.sha256(checkpoint_json.encode("utf-8")).hexdigest()
                result = None
                if result_json is not None:
                    payload = self._stored_object(result_json)
                    result = result_model.model_validate(payload)
                    self._validate_status_result(result)
                    if checkpoint is not None:
                        if (result.operation_kind != checkpoint.operation_kind
                                or result.stored_price_ids != checkpoint.stored_price_ids
                                or result.imported_prices != len(checkpoint.stored_price_ids)
                                or result.pipeline_status != checkpoint.pipeline_status
                                or result.dry_run or result.result_journal_status != "recorded"
                                or (result.stored_price_ids and result.pipeline_status == "not_started")):
                            raise ValueError("result_checkpoint_mismatch")
                if result is not None:
                    explanation = ("Gespeicherte Antwort mit damaligem Speicherbeleg; kein Nachweis des heutigen "
                                   "Preisbestands oder einer aktuellen fachlichen Freigabe.") if checkpoint else (
                        "Fruehere gespeicherte Antwort ohne Checkpointbeleg; kein nachtraeglicher Speicher-, "
                        "Bestands- oder Freigabenachweis."
                    )
                    return status_model(status="recorded", result=result, checkpoint=checkpoint,
                                        checkpoint_sha256=checkpoint_sha256, explanation=explanation)
                if checkpoint is not None:
                    if checkpoint.pipeline_status in {"completed", "failed"}:
                        raise ValueError("final_checkpoint_without_result")
                    return status_model(status="checkpointed", checkpoint=checkpoint,
                        checkpoint_sha256=checkpoint_sha256, explanation=(
                            "Damals gespeicherte Preis-IDs belegt; kein finales Auftragsergebnis. "
                            "Pipelinebeginn oder -abschluss nur gemaess Checkpoint, kein heutiger Bestandsnachweis."
                        ))
                return status_model(status="unknown_or_running", explanation=(
                    "Auftrag reserviert; Ausgang nicht dokumentiert oder noch in Arbeit. "
                    "Vor Wiederholung Zustand pruefen."
                ))
        except (RequestCancelled, RequestDeadlineExceeded):
            raise error("Auftragsstatus nicht sicher lesbar; keine Wiederholung starten.") from None
        except Exception:
            logger.error("Price backfill operation status could not be validated")
            raise error("Auftragsstatus nicht sicher lesbar; keine Wiederholung starten.") from None

    @staticmethod
    def _stored_object(raw: str) -> dict:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("operation_json_invalid")

        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("operation_json_duplicate_key")
                value[key] = item
            return value

        def invalid_constant(value):
            raise ValueError("operation_json_constant_invalid")

        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise ValueError("operation_json_invalid")
        return value

    @staticmethod
    def _validate_status_result(result) -> None:
        reasons = {FX_REFERENCE_INVALID, FX_REFERENCE_UNVERIFIED, PRICE_CANDIDATE_OUT_OF_RANGE,
                   PRICE_OUT_OF_RANGE, FX_SOURCE_UNREADABLE, PRICE_PROVIDER_ERROR,
                   "asset_not_configured", "token_risk_spam_review", "asset_usd_missing", "asset_eur_missing"}
        for job in result.jobs:
            if (job.status not in {"planned", "imported", "skipped", "failed"}
                    or job.reason is not None and job.reason not in reasons
                    or any(reason not in reasons for reason in getattr(job, "additional_reasons", []))):
                raise ValueError("operation_job_status_invalid")
        if (result.pipeline_status == "completed" and (result.pipeline is None or result.pipeline_effects != "completed")
                or result.pipeline_status == "failed"
                and (result.pipeline is not None or result.pipeline_effects != "unknown_or_partial")
                or result.pipeline_status == "not_started"
                and (result.pipeline is not None or result.pipeline_effects != "not_started")):
            raise ValueError("operation_pipeline_status_invalid")

    def _mark_pipeline_started(self, request_hash: str, operation_kind: str, stored_price_ids: list[str]) -> None:
        interrupted = (CurrentBackfillPipelineInterrupted if operation_kind == "current_portfolio"
                       else HistoricalBackfillPipelineInterrupted)
        unknown = (CurrentBackfillPipelineStartUnknown if operation_kind == "current_portfolio"
                   else HistoricalBackfillPipelineStartUnknown)
        try:
            self.store.mark_price_backfill_pipeline_started(request_hash, operation_kind)
        except (RequestCancelled, RequestDeadlineExceeded):
            raise interrupted(stored_price_ids) from None
        except Exception:
            logger.error("Price backfill pipeline start marker could not be confirmed")
            raise unknown(stored_price_ids) from None

    def _pipeline_after_prepare(self, request_hash: str, operation_kind: str,
                                stored_price_ids: list[str]) -> tuple[PipelineResult | None, str, str]:
        interrupted = (CurrentBackfillPipelineInterrupted if operation_kind == "current_portfolio"
                       else HistoricalBackfillPipelineInterrupted)
        unknown = (CurrentBackfillPipelineStartUnknown if operation_kind == "current_portfolio"
                   else HistoricalBackfillPipelineStartUnknown)
        try:
            # Same-store RLock only: no provider calls under this gate, and no
            # claim of a cross-process transaction over the whole pipeline.
            with self.store.exclusive_access():
                self._mark_pipeline_started(request_hash, operation_kind, stored_price_ids)
                try:
                    pipeline = PipelineResult.model_validate(PipelineService(self.store).rebuild_all())
                except (RequestCancelled, RequestDeadlineExceeded):
                    raise interrupted(stored_price_ids) from None
                except Exception:
                    message = ("Current portfolio price pipeline failed after price storage"
                               if operation_kind == "current_portfolio" else
                               "Historical price backfill pipeline failed after price storage")
                    logger.error(message)
                    return None, "failed", "unknown_or_partial"
                return pipeline, "completed", "completed"
        except (CurrentBackfillPipelineInterrupted, HistoricalBackfillPipelineInterrupted,
                CurrentBackfillPipelineStartUnknown, HistoricalBackfillPipelineStartUnknown):
            raise
        except (RequestCancelled, RequestDeadlineExceeded):
            raise interrupted(stored_price_ids) from None
        except Exception:
            logger.error("Price backfill pipeline gate could not be confirmed")
            raise unknown(stored_price_ids) from None

    def _prepare_prices(self, request_hash: str, operation_kind: str, prices: list[PricePointCreate]) -> list[str]:
        created = self.store.prepare_price_backfill(request_hash, operation_kind, prices)
        identifiers = [price.price_id for price in created]
        if len(identifiers) != len(prices):
            raise ValueError("price_backfill_prepare_count_mismatch")
        PriceBackfillCheckpoint.canonical_unique_ids(identifiers)
        return identifiers

    def _reserve_historical_backfill(self, *, request_id: str | None, config_path: str, v1_fx_db_path: str,
                                    provider: str, assets_filter: list[str], max_requests: int,
                                    timeout_seconds: int, confidence: Decimal) -> str:
        try:
            if request_id:
                key = self._explicit_historical_request_hash(request_id)
            else:
                with localcontext() as arithmetic:
                    arithmetic.prec = max(28, len(confidence.as_tuple().digits))
                    canonical_confidence = str(confidence.normalize())
                identity = {
                    "operation_kind": "historical", "config_path": str(resolve_project_path(config_path)),
                    "v1_fx_db_path": str(resolve_project_path(v1_fx_db_path)),
                    "provider": provider if provider in {"auto", "coingecko", "defillama"} else "auto",
                    "assets": sorted({asset.strip().upper() for asset in assets_filter if asset.strip()}),
                    "max_requests": max(0, min(max_requests, 1000)),
                    "timeout_seconds": max(3, min(timeout_seconds, 60)), "confidence": canonical_confidence,
                }
                key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            reserved = self.store.reserve_historical_price_backfill(key)
        except (RequestCancelled, RequestDeadlineExceeded):
            raise
        except Exception:
            logger.error("Historical price backfill reservation failed")
            raise HistoricalBackfillReservationUnknown("Historische Auftragsreservierung unklar; kein Preisabruf begonnen.") from None
        if reserved is not True:
            if reserved is False:
                raise HistoricalBackfillReplayBlocked("Historischer Auftrag bereits reserviert; keine Wiederholung ausgefuehrt.")
            raise HistoricalBackfillReservationUnknown("Historische Auftragsreservierung unklar; kein Preisabruf begonnen.")
        return key

    def _reserve_current_backfill(self, *, request_id: str | None, config_path: str, provider: str,
                                  assets_filter: list[str], max_requests: int, timeout_seconds: int,
                                  confidence: Decimal) -> str:
        identity = {"request_id": str(request_id)} if request_id else {
            "config_path": config_path, "provider": provider,
            "assets": sorted({asset.strip().upper() for asset in assets_filter if asset.strip()}),
            "max_requests": max_requests, "timeout_seconds": timeout_seconds, "confidence": str(confidence),
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        reserved = None
        try:
            reserved = self.store.reserve_current_price_backfill(key)
        except Exception:
            logger.error("Current portfolio price backfill reservation failed")
        if reserved is None:
            raise CurrentBackfillReservationUnknown("Auftragsreservierung unklar; keine Preisoperation begonnen.")
        if not reserved:
            raise CurrentBackfillReplayBlocked("Auftrag bereits reserviert; Zustand vor einem neuen Auftrag pruefen.")
        return key

    def _load_assets(self, config_path: str) -> list[_PriceAsset]:
        path = resolve_project_path(config_path)
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
        from steuerreport_v2.contracts.historical_prices import PriceMapping
        with self.store.connect() as con:
            configured = con.execute("select value_json from admin_settings where starts_with(key, 'price.mapping.')").fetchall()
        for row in configured:
            mapping = PriceMapping.model_validate_json(row[0], context={"stored_mapping": True})
            result.append(_PriceAsset(symbol=mapping.asset, coingecko_id=mapping.coingecko_id,
                defillama_id=mapping.defillama_id, aliases=(mapping.asset,)))
        return result

    def _token_risk_statuses(self) -> dict[str, str]:
        priority = {
            "spam_review": 4,
            "review": 3,
            "unverified_plausible": 2,
            "verified": 1,
        }
        with self.store.connect() as con:
            rows = con.execute(
                """
                select upper(coalesce(symbol, mint)), risk_status
                from jupiter_token_metadata_cache
                where coalesce(symbol, mint) is not null
                """
            ).fetchall()
        result: dict[str, str] = {}
        for asset, status in rows:
            key = str(asset).upper()
            candidate = str(status or "review")
            current = result.get(key)
            if current is None or priority.get(candidate, 3) > priority.get(current, 3):
                result[key] = candidate
        return result

    def _alias_map(self, assets: list[_PriceAsset]) -> dict[str, _PriceAsset]:
        result: dict[str, _PriceAsset] = {}
        for asset in assets:
            result[asset.symbol] = asset
            for alias in asset.aliases:
                result[alias] = asset
        return result

    def _usd_eur_rate(self, db_path: str, rate_date: str) -> Decimal:
        reference = self._usd_eur_reference(db_path, rate_date)
        return reference.rate_eur_per_usd if reference else Decimal("0")

    def _usd_eur_reference(self, db_path: str, rate_date: str) -> FxReference | None:
        path = Path(db_path).expanduser()
        if not path.exists():
            return None
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            return cache_fx_reference(con, date.fromisoformat(rate_date))

    def _timed_usd_eur_reference(self, db_path: str, rate_date: str) -> FxReference | None:
        path = Path(db_path).expanduser()
        if not path.exists():
            return None
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            columns = {row[1] for row in con.execute("pragma table_info(fx_cache)").fetchall()}
            if "source_rate_date" not in columns:
                return None
            reference = cache_fx_reference(con, date.fromisoformat(rate_date), before_day=True, require_source=True)
        return reference if reference and reference.source.strip() else None

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
            params={"date": dt.strftime("%Y-%m-%d"), "localization": "false"},
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
        if not isinstance(data, dict) or data.get("base") != "USD":
            return Decimal("0"), ""
        amount = self._decimal(data.get("amount"))
        if not amount.is_finite() or amount != 1:
            return Decimal("0"), ""
        rates = data.get("rates") if isinstance(data, dict) else None
        if not isinstance(rates, dict):
            return Decimal("0"), ""
        rate = self._decimal(rates.get("EUR"))
        if not rate.is_finite() or rate <= 0:
            return Decimal("0"), ""
        return rate, str(data.get("date") or "")

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
            result = Decimal(str(value))
            return result if result.is_finite() else Decimal("0")
        except (InvalidOperation, ValueError):
            return Decimal("0")
