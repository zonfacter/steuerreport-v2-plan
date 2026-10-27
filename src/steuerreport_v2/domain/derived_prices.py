from __future__ import annotations

from bisect import bisect_right, insort
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore

DERIVED_EVENT_QUOTE_SOURCE = "derived:event_quote"


@dataclass(frozen=True)
class DerivedPriceBackfillResult:
    deleted_existing: int
    created: int


class DerivedPriceService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def rebuild_from_event_quotes(self, max_passes: int = 4) -> DerivedPriceBackfillResult:
        deleted = self.store.delete_price_points_by_source(DERIVED_EVENT_QUOTE_SOURCE)
        history: dict[str, list[tuple[datetime, Decimal]]] = {}
        known_keys: set[tuple[str, datetime]] = set()
        for point in self.store.list_price_points(limit=1_000_000):
            asset = point.asset.upper()
            insort(history.setdefault(asset, []), (point.priced_at, point.price_eur))
            known_keys.add((asset, point.priced_at))

        derived: list[PricePointCreate] = []
        events = sorted(self.store.list_canonical_events(), key=self._event_sort_key)
        with self.store.connect() as con:
            unclassified = {row[0] for row in con.execute(
                """
                select e.event_id from canonical_events e
                join raw_objects r on r.raw_object_id = e.raw_object_id
                where e.source = 'solana_rpc' and e.event_type = 'transfer'
                  and json_extract_string(r.payload_json, '$.history_mapper_version') = '2'
                """
            ).fetchall()}
        counterflow_events = [event for event in events if event.event_id not in unclassified]
        for _ in range(max_passes):
            created_in_pass = 0
            for event in events:
                if (
                    event.quote_asset is None
                    or event.quote_quantity is None
                    or event.quantity == 0
                    or event.quote_quantity == 0
                ):
                    continue
                asset = event.asset.upper()
                quote_asset = event.quote_asset.upper()
                if asset == quote_asset:
                    continue

                asset_quantity = abs(event.quantity)
                quote_quantity = abs(event.quote_quantity)
                if quote_asset == "EUR":
                    created_in_pass += self._append_price(
                        history=history,
                        known_keys=known_keys,
                        derived=derived,
                        asset=asset,
                        priced_at=event.event_time,
                        price_eur=quote_quantity / asset_quantity,
                        confidence=Decimal("0.95"),
                    )
                    continue
                if asset == "EUR":
                    created_in_pass += self._append_price(
                        history=history,
                        known_keys=known_keys,
                        derived=derived,
                        asset=quote_asset,
                        priced_at=event.event_time,
                        price_eur=asset_quantity / quote_quantity,
                        confidence=Decimal("0.95"),
                    )
                    continue
                quote_price = self._price_at_or_before(history, quote_asset, event.event_time)
                if quote_price is not None:
                    created_in_pass += self._append_price(
                        history=history,
                        known_keys=known_keys,
                        derived=derived,
                        asset=asset,
                        priced_at=event.event_time,
                        price_eur=(quote_quantity * quote_price) / asset_quantity,
                        confidence=Decimal("0.95")
                        if quote_asset == "EUR"
                        else Decimal("0.85"),
                    )
                    continue

                asset_price = self._price_at_or_before(history, asset, event.event_time)
                if asset_price is None:
                    continue
                created_in_pass += self._append_price(
                    history=history,
                    known_keys=known_keys,
                    derived=derived,
                    asset=quote_asset,
                    priced_at=event.event_time,
                    price_eur=(asset_quantity * asset_price) / quote_quantity,
                    confidence=Decimal("0.80"),
                )
            created_in_pass += self._append_group_counterflow_prices(
                events=counterflow_events,
                history=history,
                known_keys=known_keys,
                derived=derived,
            )
            if created_in_pass == 0:
                break

        self.store.add_price_points(derived)
        return DerivedPriceBackfillResult(deleted_existing=deleted, created=len(derived))

    def _append_group_counterflow_prices(
        self,
        *,
        events: list[CanonicalEvent],
        history: dict[str, list[tuple[datetime, Decimal]]],
        known_keys: set[tuple[str, datetime]],
        derived: list[PricePointCreate],
    ) -> int:
        grouped: dict[tuple[str, str, datetime], list[CanonicalEvent]] = {}
        for event in events:
            if event.quantity == 0 or event.event_type == "fee":
                continue
            grouped.setdefault(
                (event.source, event.account or "unassigned", event.event_time),
                [],
            ).append(event)

        created = 0
        for (_, _, event_time), group_events in grouped.items():
            positive: dict[str, Decimal] = {}
            negative: dict[str, Decimal] = {}
            for event in group_events:
                asset = event.asset.upper()
                if event.quantity > 0:
                    positive[asset] = positive.get(asset, Decimal("0")) + event.quantity
                elif event.quantity < 0:
                    negative[asset] = negative.get(asset, Decimal("0")) + abs(event.quantity)

            positive_assets = [asset for asset in positive if asset != "EUR" and positive[asset] > 0]
            if len(positive_assets) != 1:
                continue
            target_asset = positive_assets[0]
            if (target_asset, event_time) in known_keys:
                continue

            value_eur = Decimal("0")
            for quote_asset, quote_quantity in negative.items():
                if quote_asset == target_asset:
                    continue
                quote_price = self._price_at_or_before(history, quote_asset, event_time)
                if quote_price is None:
                    value_eur = Decimal("0")
                    break
                value_eur += quote_quantity * quote_price
            if value_eur <= 0:
                continue

            created += self._append_price(
                history=history,
                known_keys=known_keys,
                derived=derived,
                asset=target_asset,
                priced_at=event_time,
                price_eur=value_eur / positive[target_asset],
                confidence=Decimal("0.90"),
            )
        return created

    def _append_price(
        self,
        *,
        history: dict[str, list[tuple[datetime, Decimal]]],
        known_keys: set[tuple[str, datetime]],
        derived: list[PricePointCreate],
        asset: str,
        priced_at: datetime,
        price_eur: Decimal,
        confidence: Decimal,
    ) -> int:
        if asset == "EUR" or price_eur <= 0:
            return 0
        key = (asset, priced_at)
        if key in known_keys:
            return 0
        known_keys.add(key)
        insort(history.setdefault(asset, []), (priced_at, price_eur))
        derived.append(
            PricePointCreate(
                asset=asset,
                price_eur=price_eur,
                priced_at=priced_at,
                source=DERIVED_EVENT_QUOTE_SOURCE,
                confidence=confidence,
            )
        )
        return 1

    @staticmethod
    def _event_sort_key(event: CanonicalEvent) -> tuple[object, ...]:
        return (
            event.event_time,
            event.source,
            event.account or "",
            event.wallet or "",
            event.tx_id or "",
            event.source_ref or "",
            event.event_type,
            event.asset,
            event.quote_asset or "",
            event.quantity,
            event.quote_quantity or Decimal("0"),
            event.fee_asset or "",
            event.fee_quantity or Decimal("0"),
        )

    def _price_at_or_before(
        self,
        history: dict[str, list[tuple[datetime, Decimal]]],
        asset: str,
        priced_at: datetime,
    ) -> Decimal | None:
        if asset == "EUR":
            return Decimal("1")
        asset_history = history.get(asset)
        if not asset_history:
            return None
        index = bisect_right(asset_history, (priced_at, Decimal("Infinity"))) - 1
        if index < 0:
            return None
        return asset_history[index][1]
