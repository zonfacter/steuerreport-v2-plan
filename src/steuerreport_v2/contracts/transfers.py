from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class TransferCandidate(BaseModel):
    asset: str
    score: int
    status: str
    amount_out: Decimal
    amount_in: Decimal
    amount_delta: Decimal
    out_event_id: str
    in_event_id: str
    out_time: datetime
    in_time: datetime
    time_delta_seconds: int
    out_account: str | None = None
    in_account: str | None = None
    out_source: str
    in_source: str
    out_tx_id: str | None = None
    in_tx_id: str | None = None
    reasons: list[str]
    warnings: list[str]


class TransferCandidateReport(BaseModel):
    candidates_count: int
    assets: list[str]
    candidates: list[TransferCandidate]
