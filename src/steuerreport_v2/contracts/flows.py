from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class FlowEntry(BaseModel):
    flow_id: str
    event_id: str
    event_time: datetime
    source_node: str
    target_node: str
    asset: str
    quantity: Decimal
    value_eur: Decimal | None = None
    price_source: str | None = None


class NetFlowEdge(BaseModel):
    source_node: str
    target_node: str
    value_eur: Decimal
    event_count: int


class NetFlowSummary(BaseModel):
    year: int | None = None
    available_years: list[int] = []
    total_visible_value_eur: Decimal
    edges: list[NetFlowEdge]
    missing_price_assets: list[str]
