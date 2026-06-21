from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class DerivativeLine(BaseModel):
    derivative_line_id: str
    event_id: str
    source: str
    source_ref: str | None = None
    event_time: datetime
    account: str | None = None
    asset: str
    quantity: Decimal
    price_eur: Decimal
    value_eur: Decimal
    price_source: str | None = None


class DerivativeRunSummary(BaseModel):
    run_id: str
    derivative_lines_count: int
    realized_pnl_eur: Decimal
    missing_price_count: int
    created_at: datetime


class DerivativeRunResult(BaseModel):
    lines: list[DerivativeLine]
    summary: DerivativeRunSummary
