from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.db.duckdb_store import DuckDbStore


TOLERANCE = Decimal("0.000000000001")


def locked_redemption_clawback_reward_event_ids(
    store: DuckDbStore,
    events: list[CanonicalEvent],
) -> dict[str, frozenset[str]]:
    payloads = _provider_payloads(store)
    rewards_by_asset: defaultdict[str, list[CanonicalEvent]] = defaultdict(list)
    subscriptions_by_asset: defaultdict[str, list[CanonicalEvent]] = defaultdict(
        list
    )
    losses: list[CanonicalEvent] = []
    for event in events:
        if event.asset.upper() == "EUR":
            continue
        if _is_loss(event):
            losses.append(event)
        elif event.event_type == "reward" and event.quantity > 0:
            rewards_by_asset[event.asset.upper()].append(event)
        elif (
            event.source.lower() == "binance_simple_earn_api"
            and event.event_type == "transfer"
            and event.quantity > 0
        ):
            subscriptions_by_asset[event.asset.upper()].append(event)

    result: dict[str, frozenset[str]] = {}
    for loss in losses:
        payload = payloads.get(loss.event_id, {})
        position_id = str(payload.get("position_id") or "").strip()
        target = abs(loss.quantity)
        direct_candidates = [
            event
            for event in rewards_by_asset[loss.asset.upper()]
            if event.source.lower() == "binance_simple_earn_api"
            and event.event_time <= loss.event_time
            and _record_type(payloads.get(event.event_id, {})) == "locked_rewards"
            and (
                not position_id
                or str(payloads.get(event.event_id, {}).get("position_id") or "").strip()
                == position_id
            )
        ]
        selected = _exact_reward_subset(direct_candidates, target)
        if not selected:
            original_amount = _decimal(payload.get("original_amount"))
            subscriptions = [
                event
                for event in subscriptions_by_asset[loss.asset.upper()]
                if event.event_time <= loss.event_time
                and _record_type(payloads.get(event.event_id, {}))
                == "locked_subscription"
                and (
                    original_amount is None
                    or abs(event.quantity - original_amount) <= TOLERANCE
                )
            ]
            if subscriptions:
                subscription = max(subscriptions, key=lambda event: event.event_time)
                ledger_candidates = [
                    event
                    for event in rewards_by_asset[loss.asset.upper()]
                    if event.source.lower() == "binance"
                    and subscription.event_time <= event.event_time <= loss.event_time
                    and "simple earn locked rewards"
                    in str(
                        payloads.get(event.event_id, {}).get("operation") or ""
                    ).lower()
                ]
                selected = _exact_reward_subset(ledger_candidates, target)
        if selected:
            result[loss.event_id] = frozenset(
                event.event_id for event in selected
            )
    return result


def _provider_payloads(store: DuckDbStore) -> dict[str, dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select e.event_id, r.payload_json
            from canonical_events e
            join raw_objects r on r.raw_object_id = e.raw_object_id
            where lower(e.source) in ('binance', 'binance_simple_earn_api')
              and (
                    e.event_type = 'reward'
                 or e.source_ref like 'locked_subscription:%'
                 or e.source_ref like 'locked_redemption_loss:%'
              )
            """
        ).fetchall()
    result: dict[str, dict[str, object]] = {}
    for event_id, payload_json in rows:
        try:
            payload = json.loads(payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        result[str(event_id)] = {
            str(key).strip().lower(): value for key, value in payload.items()
        }
    return result


def _exact_reward_subset(
    candidates: list[CanonicalEvent],
    target: Decimal,
) -> list[CanonicalEvent]:
    if abs(sum((event.quantity for event in candidates), Decimal("0")) - target) <= TOLERANCE:
        return sorted(candidates, key=_event_order)
    selected: list[CanonicalEvent] = []
    total = Decimal("0")
    for event in sorted(candidates, key=_event_order, reverse=True):
        if total + event.quantity > target + TOLERANCE:
            continue
        selected.append(event)
        total += event.quantity
        if abs(total - target) <= TOLERANCE:
            return sorted(selected, key=_event_order)
    return []


def _is_loss(event: CanonicalEvent) -> bool:
    return (
        event.source.strip().lower() == "binance_simple_earn_api"
        and event.event_type == "fee"
        and event.quantity < 0
        and str(event.source_ref or "").startswith("locked_redemption_loss:")
    )


def _record_type(payload: dict[str, object]) -> str:
    return str(payload.get("record_type") or payload.get("record type") or "").lower()


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _event_order(event: CanonicalEvent) -> tuple[datetime, str]:
    event_time = (
        event.event_time.replace(tzinfo=timezone.utc)
        if event.event_time.tzinfo is None
        else event.event_time.astimezone(timezone.utc)
    )
    return event_time, event.event_id
