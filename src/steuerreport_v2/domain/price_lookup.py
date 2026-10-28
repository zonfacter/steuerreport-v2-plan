from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PriceLookupCandidate, PriceLookupDecision, PricePoint
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_policy import (
    DERIVED_PRICE_SOURCE_PREFIXES as DERIVED_PRICE_SOURCE_PREFIXES,
    POLICY_ID,
    POLICY_VERSION,
    as_utc,
    is_derived_source,
    price_rejection_reason,
    price_selection_key,
)


FIAT_EUR_ASSETS = {"EUR"}


@dataclass(frozen=True)
class LastKnownPriceDiagnostic:
    asset: str
    cutoff: datetime
    point: PricePoint | None
    policy_id: str = "diagnostic_last_known_non_derived_not_after"
    policy_version: int = 1


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
        points = store.list_price_points(limit=None)
        by_asset: dict[str, list[PricePoint]] = {}
        for point in points:
            point = point.model_copy(update={"priced_at": as_utc(point.priced_at)})
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
        priced_at = as_utc(priced_at)
        fiat = fiat_price_point(asset, priced_at)
        if fiat is not None:
            return fiat
        asset_points = self._points.get(asset.upper())
        if not asset_points:
            return None
        times = self._times[asset.upper()]
        start = bisect_left(times, priced_at.replace(hour=0, minute=0, second=0, microsecond=0))
        end = bisect_right(times, priced_at)
        candidates = [
            point for point in asset_points[start:end]
            if price_rejection_reason(point, priced_at, allow_derived=allow_derived) is None
        ]
        if not candidates:
            return None

        same_day_primary = [
            point
            for point in candidates
            if not self.is_derived_source(point.source)
        ]
        if same_day_primary:
            return max(same_day_primary, key=self._selection_key)
        return max(candidates, key=self._selection_key)

    def last_known_for_diagnostics(
        self, asset: str, priced_at: datetime,
    ) -> LastKnownPriceDiagnostic:
        """Reference only: never a replacement for an admitted historical price."""
        cutoff = as_utc(priced_at)
        point = fiat_price_point(asset, cutoff)
        if point is None:
            point = max((
                candidate for candidate in self._points.get(asset.upper(), [])
                if candidate.priced_at <= cutoff and candidate.price_eur > 0
                and not self.is_derived_source(candidate.source)
            ), key=self._selection_key, default=None)
        return LastKnownPriceDiagnostic(asset=asset.upper(), cutoff=cutoff, point=point)

    def explain(
        self,
        asset: str,
        priced_at: datetime,
        *,
        allow_derived: bool = True,
        candidate_limit: int = 50,
    ) -> PriceLookupDecision:
        """Bounded diagnostic view; selected_price always uses the normal selector."""
        event_time = as_utc(priced_at)
        selected = self.at_or_before(asset, event_time, allow_derived=allow_derived)
        fiat = asset.upper() in FIAT_EUR_ASSETS
        points = [selected] if fiat else self._points.get(asset.upper(), [])
        limit = max(0, min(candidate_limit, 1000))
        # Show the selected point first, then nearby candidates on either side.
        ordered = sorted(points, key=self._selection_key, reverse=True)
        ordered.sort(key=lambda point: (
            point is not selected,
            abs((point.priced_at - event_time).total_seconds()),
        ))
        return PriceLookupDecision(
            policy_id=POLICY_ID,
            policy_version=POLICY_VERSION,
            asset=asset.upper(),
            event_time=event_time,
            allow_derived=allow_derived,
            status="fiat" if fiat else "selected" if selected is not None else "missing",
            rejection_reason=(
                None if selected is not None else "no_eligible_candidate" if points else "no_candidates"
            ),
            selected_price=selected,
            candidates=[PriceLookupCandidate(
                price=point,
                rejection_reason=price_rejection_reason(point, event_time, allow_derived=allow_derived),
                selected=point is selected,
                provenance_status="synthetic_fiat_identity" if fiat else "not_linked",
            ) for point in ordered[:limit]],
            candidate_count=len(points),
            candidates_truncated=len(points) > limit,
        )

    @staticmethod
    def is_derived_source(source: str) -> bool:
        return is_derived_source(source)

    @classmethod
    def _selection_key(
        cls,
        point: PricePoint,
    ) -> tuple[datetime, int, Decimal, str, Decimal, str]:
        return price_selection_key(point)

    @staticmethod
    def _source_priority(source: str) -> int:
        if HistoricalPriceLookup.is_derived_source(source):
            return 0
        return 10
