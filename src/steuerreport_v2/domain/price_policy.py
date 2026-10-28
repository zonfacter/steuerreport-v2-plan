"""Konservative technische Ersatzkursregel, keine steuerliche Methodenfreigabe."""

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate


POLICY_ID = "historical_same_utc_day_not_after_event"
POLICY_VERSION = 1
DERIVED_PRICE_SOURCE_PREFIXES = ("derived:",)
SOURCE_WHITESPACE = (
    " \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_derived_source(source: str) -> bool:
    return source.strip().lower().startswith(DERIVED_PRICE_SOURCE_PREFIXES)


def price_rejection_reason(
    point: PricePointCreate, event_time: datetime, *, allow_derived: bool = True,
) -> str | None:
    point_time, event_time = as_utc(point.priced_at), as_utc(event_time)
    if point.price_eur <= 0:
        return "non_positive"
    if point_time > event_time:
        return "future"
    if point_time.date() != event_time.date():
        return "different_utc_day"
    if not allow_derived and is_derived_source(point.source):
        return "derived_disallowed"
    return None


def price_selection_key(point: PricePointCreate) -> tuple[datetime, int, Decimal, str, Decimal, str]:
    return (
        as_utc(point.priced_at),
        0 if is_derived_source(point.source) else 10,
        point.confidence,
        point.source,
        point.price_eur,
        getattr(point, "price_id", ""),
    )


def eligible_price_sql(*, price: str, event_time: str, allow_derived: str) -> str:
    # Only internal SQL expressions belong here, never request values.
    # DuckDB's default trim removes spaces only; match Python str.strip instead.
    normalized_source = f"lower(trim({price}.source, '{SOURCE_WHITESPACE}'))"
    return f"""(
        {price}.price_eur > 0
        and {price}.priced_at <= {event_time}
        and cast({price}.priced_at as date) = cast({event_time} as date)
        and ({allow_derived} or not starts_with({normalized_source}, 'derived:'))
    )"""
