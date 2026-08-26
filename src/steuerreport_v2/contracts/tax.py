from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TaxLot(BaseModel):
    lot_id: str
    asset: str
    acquired_at: datetime
    quantity_total: Decimal
    quantity_remaining: Decimal
    cost_basis_eur_total: Decimal
    source_event_id: str
    pool_id: str | None = None
    origin_lot_id: str | None = None
    fifo_method: str = "global_asset_with_wallet_fifo_evidence_overlay_v1"


class TaxLine(BaseModel):
    tax_line_id: str
    asset: str
    acquired_at: datetime
    disposed_at: datetime
    quantity: Decimal
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_days: int
    source_event_id: str
    lot_id: str
    pool_id: str | None = None
    acquisition_source_event_id: str | None = None
    origin_lot_id: str | None = None
    fifo_method: str = "global_asset_with_wallet_fifo_evidence_overlay_v1"


class TaxUnmatchedDisposal(BaseModel):
    unmatched_id: str
    source_event_id: str
    source: str
    source_ref: str | None = None
    raw_object_id: str | None = None
    event_time: datetime
    event_type: str
    account: str | None = None
    asset: str
    quantity: Decimal
    matched_quantity: Decimal
    missing_quantity: Decimal
    available_before: Decimal
    proceeds_total_eur: Decimal


class TaxRunResult(BaseModel):
    lots: list[TaxLot]
    tax_lines: list[TaxLine]
    unmatched_disposals: int
    unmatched: list[TaxUnmatchedDisposal] = []


class TaxRunSummary(BaseModel):
    run_id: str
    tax_lines_count: int
    unmatched_disposals: int
    created_at: datetime
    fifo_method: str = "global_asset_with_wallet_fifo_evidence_overlay_v1"
    input_fingerprint_digest: str | None = None


class TaxHoldingPeriodLot(BaseModel):
    lot_id: str
    asset: str
    acquired_at: datetime
    tax_free_at: datetime
    days_until_tax_free: int
    bucket: str
    quantity_remaining: Decimal
    cost_basis_eur_remaining: Decimal
    current_price_eur: Decimal
    current_value_eur: Decimal
    unrealized_gain_loss_eur: Decimal
    price_source: str
    priced_at: datetime
    source_event_id: str
    source: str | None = None
    account: str | None = None


class TaxHoldingPeriodBucket(BaseModel):
    bucket: str
    label: str
    lots_count: int = 0
    value_eur: Decimal = Decimal("0")
    assets: list[str] = Field(default_factory=list)


class TaxHoldingPeriodReport(BaseModel):
    generated_at: datetime
    as_of: datetime
    min_value_eur: Decimal
    visible_lots_count: int = 0
    hidden_dust_lots_count: int = 0
    missing_price_assets: list[str] = Field(default_factory=list)
    tax_free_now_value_eur: Decimal = Decimal("0")
    next_7_days_value_eur: Decimal = Decimal("0")
    next_30_days_value_eur: Decimal = Decimal("0")
    next_7_months_value_eur: Decimal = Decimal("0")
    next_year_value_eur: Decimal = Decimal("0")
    buckets: list[TaxHoldingPeriodBucket] = Field(default_factory=list)
    lots: list[TaxHoldingPeriodLot] = Field(default_factory=list)
    methodology: str
