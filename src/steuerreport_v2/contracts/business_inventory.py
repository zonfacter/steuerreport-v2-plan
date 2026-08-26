from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


BusinessRewardOriginStatus = Literal[
    "potential_business_inventory",
    "origin_classification_review",
    "separate_income_review",
    "non_reward_origin",
    "missing_origin",
]


class BusinessRewardInventoryReviewRow(BaseModel):
    disposal_year: int
    asset: str
    origin_source: str | None = None
    origin_event_type: str | None = None
    origin_account: str | None = None
    origin_events_count: int = 0
    tax_lines_count: int = 0
    quantity_disposed: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    disposal_proceeds_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")
    first_disposal_at: str | None = None
    last_disposal_at: str | None = None
    sample_origin_event_id: str | None = None
    sample_disposal_event_id: str | None = None
    classification: BusinessRewardOriginStatus
    blocks_private_fifo_classification: bool = False
    reason: str


class BusinessRewardInventoryReviewReport(BaseModel):
    generated_at: str
    assets: list[str] = Field(default_factory=list)
    affected_years: list[int] = Field(default_factory=list)
    strict_ready: bool = False
    total_tax_lines_count: int = 0
    potential_business_tax_lines_count: int = 0
    unresolved_tax_lines_count: int = 0
    potential_business_acquisition_cost_eur: Decimal = Decimal("0")
    potential_business_proceeds_eur: Decimal = Decimal("0")
    potential_business_gain_loss_eur: Decimal = Decimal("0")
    rows: list[BusinessRewardInventoryReviewRow] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
