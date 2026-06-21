from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePoint
from steuerreport_v2.db.duckdb_store import DuckDbStore


FIAT_EUR_ASSETS = {"EUR"}
DERIVED_PRICE_SOURCE_PREFIXES = ("derived:",)


def fiat_price_point(asset: str, priced_at: datetime | None = None) -> PricePoint | None:
    upper = asset.upper()
    if upper not in FIAT_EUR_ASSETS:
        return None
    return PricePoint(
        price_id=f"synthetic:{upper}:EUR",
        asset=upper,
        price_eur=Decimal("1"),
        priced_at=priced_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
        source="fiat:EUR",
        confidence=Decimal("1"),
    )


class HistoricalPriceLookup:
    def __init__(self, store: DuckDbStore) -> None:
        points = store.list_price_points(limit=1_000_000)
        by_asset: dict[str, list[PricePoint]] = {}
        for point in points:
            if point.price_eur <= 0:
                continue
            if point.priced_at.tzinfo is None:
                point = point.model_copy(
                    update={"priced_at": point.priced_at.replace(tzinfo=timezone.utc)}
                )
            by_asset.setdefault(point.asset.upper(), []).append(point)
        self._points = {
            asset: sorted(
                asset_points,
                key=lambda item: (
                    item.priced_at,
                    self._source_priority(item.source),
                    item.confidence,
                    item.price_id,
                ),
            )
            for asset, asset_points in by_asset.items()
        }
        self._times = {
            asset: [point.priced_at for point in asset_points]
            for asset, asset_points in self._points.items()
        }

    def at_or_before(
        self,
        asset: str,
        priced_at: datetime,
        *,
        allow_derived: bool = True,
    ) -> PricePoint | None:
        if priced_at.tzinfo is None:
            priced_at = priced_at.replace(tzinfo=timezone.utc)
        priced_at = priced_at.astimezone(timezone.utc)
        fiat = fiat_price_point(asset, priced_at)
        if fiat is not None:
            return fiat
        asset_points = self._points.get(asset.upper())
        if not asset_points:
            return None
        index = bisect_right(self._times[asset.upper()], priced_at) - 1
        if index < 0:
            return None
        candidates = asset_points[: index + 1]
        if not allow_derived:
            candidates = [
                point for point in candidates if not self.is_derived_source(point.source)
            ]
            if not candidates:
                return None

        same_day_primary = [
            point
            for point in candidates
            if point.priced_at.date() == priced_at.date()
            and not self.is_derived_source(point.source)
        ]
        if same_day_primary:
            return max(same_day_primary, key=self._selection_key)
        return max(candidates, key=self._selection_key)

    @staticmethod
    def is_derived_source(source: str) -> bool:
        normalized = source.strip().lower()
        return normalized.startswith(DERIVED_PRICE_SOURCE_PREFIXES)

    @classmethod
    def _selection_key(cls, point: PricePoint) -> tuple[datetime, int, Decimal, str]:
        return (
            point.priced_at,
            cls._source_priority(point.source),
            point.confidence,
            point.price_id,
        )

    @staticmethod
    def _source_priority(source: str) -> int:
        if HistoricalPriceLookup.is_derived_source(source):
            return 0
        return 10
