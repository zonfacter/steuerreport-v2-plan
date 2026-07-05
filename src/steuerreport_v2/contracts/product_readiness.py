from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


ProductReadinessStatus = Literal["ready", "review", "blocked", "setup_required"]
ProductReadinessSeverity = Literal["ok", "info", "warning", "blocker"]


class ProductReadinessCheck(BaseModel):
    key: str
    label: str
    status: ProductReadinessSeverity
    detail: str
    next_action: str
    action_path: str | None = None
    count: int = 0


class ProductReadinessSource(BaseModel):
    source_id: str
    label: str
    connector_id: str
    source_type: str
    status: ProductReadinessSeverity
    credential_status: str = "not_required"
    live_status: str = "missing"
    ledger_value_eur: Decimal = Decimal("0")
    live_value_eur: Decimal | None = None
    delta_value_eur: Decimal | None = None
    open_issues: int = 0
    next_action: str
    action_path: str


class ProductReadinessReport(BaseModel):
    generated_at: datetime
    overall_status: ProductReadinessStatus
    can_prepare_tax_report: bool = False
    can_file_without_review: bool = False
    headline: str
    next_action: str
    next_action_path: str
    checks: list[ProductReadinessCheck] = Field(default_factory=list)
    sources: list[ProductReadinessSource] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_ready_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    setup_required_sources: int = 0
    review_items_count: int = 0
    blocking_items_count: int = 0
    methodology: str
