from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BinanceEarnHistoryApiRecord(BaseModel):
    endpoint: str
    asset: str | None = None
    product_id: str | None = None
    position_id: str | None = None
    record_type: str
    payload: dict[str, object] = Field(default_factory=dict)


class BinanceEarnHistoryApiRequest(BaseModel):
    endpoint: str
    record_type: str
    asset: str | None = None
    product_id: str | None = None
    position_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    pages_requested: int = 0
    records: int = 0
    total: int | None = None
    status: str
    error: str | None = None


class BinanceEarnHistoryApiPreview(BaseModel):
    generated_at: datetime
    source_id: str = "binance"
    credential_status: str
    since: datetime
    until: datetime
    assets: list[str] = Field(default_factory=list)
    requests: list[BinanceEarnHistoryApiRequest] = Field(default_factory=list)
    records: list[BinanceEarnHistoryApiRecord] = Field(default_factory=list)
    records_returned: int = 0
    records_available_hint: int = 0
    truncated: bool = False
    methodology: str


class BinanceCapitalWithdrawalRecord(BaseModel):
    endpoint: str
    asset: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class BinanceCapitalWithdrawalRequest(BaseModel):
    endpoint: str
    asset: str | None = None
    window_start: datetime
    window_end: datetime
    records: int = 0
    status: str
    error: str | None = None


class BinanceCapitalWithdrawalPreview(BaseModel):
    generated_at: datetime
    source_id: str = "binance"
    credential_status: str
    since: datetime
    until: datetime
    assets: list[str] = Field(default_factory=list)
    requests: list[BinanceCapitalWithdrawalRequest] = Field(default_factory=list)
    records: list[BinanceCapitalWithdrawalRecord] = Field(default_factory=list)
    records_returned: int = 0
    methodology: str
