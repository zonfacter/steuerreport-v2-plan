from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

EventType = Literal[
    "trade",
    "transfer",
    "fee",
    "reward",
    "income",
    "staking",
    "mining",
    "derivative",
    "unknown",
]


class CanonicalEventCreate(BaseModel):
    source: str
    source_ref: str | None = None
    event_time: datetime
    event_type: EventType
    asset: str
    quantity: Decimal
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    fee_asset: str | None = None
    fee_quantity: Decimal | None = None
    tx_id: str | None = None
    wallet: str | None = None
    account: str | None = None
    confidence: Decimal = Decimal("1.0")
    raw_object_id: str | None = None


class CanonicalEvent(CanonicalEventCreate):
    event_id: str
