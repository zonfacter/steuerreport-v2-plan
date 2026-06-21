from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BitgetWithdrawalRecord(BaseModel):
    endpoint: str
    asset: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class BitgetWithdrawalRequest(BaseModel):
    endpoint: str
    asset: str | None = None
    window_start: datetime
    window_end: datetime
    page_no: int = 1
    records: int = 0
    status: str
    error: str | None = None


class BitgetWithdrawalPreview(BaseModel):
    generated_at: datetime
    source_id: str = "bitget"
    credential_status: str
    since: datetime
    until: datetime
    assets: list[str] = Field(default_factory=list)
    requests: list[BitgetWithdrawalRequest] = Field(default_factory=list)
    records: list[BitgetWithdrawalRecord] = Field(default_factory=list)
    records_returned: int = 0
    methodology: str

