"""Reine ID-Herkunftsaufloesung; kein Beleg fuer Sphaere oder Kostenbasis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Protocol
from datetime import datetime

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.domain.tax_time import as_utc


POLICY_ID = "linked_lot_origin_v1"


class _Lot(Protocol):
    lot_id: str
    asset: str
    acquired_at: datetime
    source_event_id: str
    origin_lot_id: str | None
    pool_id: str | None


class _Line(Protocol):
    lot_id: str
    asset: str
    acquired_at: datetime | None
    disposed_at: datetime
    acquisition_source_event_id: str | None
    origin_lot_id: str | None
    pool_id: str | None


@dataclass(frozen=True)
class LotOriginTrace:
    status: Literal["direct", "carried", "unresolved"]
    lot_ids: tuple[str, ...]
    direct_event_id: str | None
    origin_event_id: str | None
    origin_asset: str | None
    reason: str | None


class LotOriginIndex:
    MAX_DEPTH = 64

    def __init__(self, lots: Iterable[_Lot], events: Iterable[CanonicalEvent]) -> None:
        self._lots: dict[str, _Lot] = {}
        self._events: dict[str, CanonicalEvent] = {}
        self._duplicate_lots: set[str] = set()
        self._duplicate_events: set[str] = set()
        for lot in lots:
            if lot.lot_id in self._lots:
                self._duplicate_lots.add(lot.lot_id)
            self._lots[lot.lot_id] = lot
        for event in events:
            if event.event_id in self._events:
                self._duplicate_events.add(event.event_id)
            self._events[event.event_id] = event

    def resolve(self, line: _Line) -> LotOriginTrace:
        path: list[str] = []
        seen: set[str] = set()
        direct = None

        def unresolved(reason: str) -> LotOriginTrace:
            return LotOriginTrace("unresolved", tuple(path), direct, None, None, reason)

        lot_id = line.lot_id
        acquired_at = None
        while True:
            if lot_id in seen:
                return unresolved("lot_cycle")
            if len(path) >= self.MAX_DEPTH:
                return unresolved("lot_depth_exceeded")
            path.append(lot_id)
            seen.add(lot_id)
            if lot_id in self._duplicate_lots:
                return unresolved("duplicate_lot_id")
            lot = self._lots.get(lot_id)
            if lot is None:
                return unresolved("missing_lot" if len(path) == 1 else "missing_origin_lot")
            if len(path) == 1:
                direct = lot.source_event_id or None
                acquired_at = as_utc(lot.acquired_at)
                if line.asset.upper() != lot.asset.upper():
                    return unresolved("line_lot_asset_conflict")
                if line.pool_id and line.pool_id != lot.pool_id:
                    return unresolved("line_lot_pool_conflict")
                if (line.acquisition_source_event_id
                        and line.acquisition_source_event_id != direct):
                    return unresolved("line_lot_source_conflict")
                if line.origin_lot_id and line.origin_lot_id != lot.origin_lot_id:
                    return unresolved("line_lot_origin_conflict")
                # A nullable legacy line date may use its actual lot, never a guessed date.
                if line.acquired_at is not None and as_utc(line.acquired_at) != acquired_at:
                    return unresolved("line_lot_acquisition_conflict")
                if as_utc(line.disposed_at) < acquired_at:
                    return unresolved("disposal_before_acquisition")
            if as_utc(lot.acquired_at) != acquired_at:
                return unresolved("carried_acquisition_conflict")
            if lot.source_event_id in self._duplicate_events:
                return unresolved("duplicate_event_id")
            event = self._events.get(lot.source_event_id)
            if event is None:
                return unresolved("missing_source_event")
            event_at = as_utc(event.event_time)
            if event_at < acquired_at or event_at > as_utc(line.disposed_at):
                return unresolved("source_event_time_conflict")
            if not self._acquires(event, lot.asset):
                return unresolved("source_event_asset_conflict")
            if not lot.origin_lot_id:
                if event_at != acquired_at:
                    return unresolved("root_acquisition_time_conflict")
                return LotOriginTrace("direct" if len(path) == 1 else "carried",
                                      tuple(path), direct, event.event_id, lot.asset.upper(), None)
            lot_id = lot.origin_lot_id

    @staticmethod
    def _acquires(event: CanonicalEvent, asset: str) -> bool:
        asset = asset.upper()
        if event.asset.upper() == asset and event.quantity > 0:
            return True
        return (event.event_type == "trade" and event.quantity < 0
                and (event.quote_asset or "").upper() == asset
                and event.quote_quantity is not None and event.quote_quantity != 0)
