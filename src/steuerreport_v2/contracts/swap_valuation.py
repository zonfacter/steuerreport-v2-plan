from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


CryptoSwapValuationStatus = Literal[
    "aligned_received_primary",
    "policy_mismatch_no_material_delta",
    "material_delta",
    "received_price_fallback_review",
    "missing_both_prices",
]


class CryptoSwapValuationDeltaRow(BaseModel):
    event_id: str
    reporting_year: int
    event_time: str
    source: str
    source_ref: str | None = None
    account: str | None = None
    tx_id: str | None = None
    received_asset: str
    received_quantity: Decimal
    given_asset: str
    given_quantity: Decimal
    current_basis: str
    bmf_preview_basis: str
    current_value_eur: Decimal = Decimal("0")
    bmf_preview_value_eur: Decimal = Decimal("0")
    value_delta_eur: Decimal = Decimal("0")
    received_price_eur: Decimal | None = None
    received_price_source: str | None = None
    received_priced_at: str | None = None
    received_price_confidence: Decimal | None = None
    given_price_eur: Decimal | None = None
    given_price_source: str | None = None
    given_priced_at: str | None = None
    given_price_confidence: Decimal | None = None
    status: CryptoSwapValuationStatus
    blocks_bmf_valuation: bool = False
    reason: str


class CryptoSwapValuationReviewReport(BaseModel):
    generated_at: str
    year: int | None = None
    strict_ready: bool = False
    candidates_count: int = 0
    aligned_count: int = 0
    policy_mismatch_count: int = 0
    material_delta_count: int = 0
    received_price_fallback_review_count: int = 0
    missing_both_prices_count: int = 0
    current_value_eur: Decimal = Decimal("0")
    bmf_preview_value_eur: Decimal = Decimal("0")
    signed_value_delta_eur: Decimal = Decimal("0")
    absolute_value_delta_eur: Decimal = Decimal("0")
    affected_years: list[int] = Field(default_factory=list)
    rows_returned: int = 0
    rows: list[CryptoSwapValuationDeltaRow] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    current_policy: str
    bmf_preview_policy: str
    methodology: str


class CryptoSwapFifoParallelYearRow(BaseModel):
    year: int
    current_gain_loss_eur: Decimal = Decimal("0")
    preview_gain_loss_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    current_short_holding_gain_loss_eur: Decimal = Decimal("0")
    preview_short_holding_gain_loss_eur: Decimal = Decimal("0")
    short_holding_gain_loss_delta_eur: Decimal = Decimal("0")
    current_long_holding_gain_loss_eur: Decimal = Decimal("0")
    preview_long_holding_gain_loss_eur: Decimal = Decimal("0")
    long_holding_gain_loss_delta_eur: Decimal = Decimal("0")
    current_proceeds_eur: Decimal = Decimal("0")
    preview_proceeds_eur: Decimal = Decimal("0")
    current_acquisition_cost_eur: Decimal = Decimal("0")
    preview_acquisition_cost_eur: Decimal = Decimal("0")
    current_tax_lines_count: int = 0
    preview_tax_lines_count: int = 0


class CryptoSwapFifoParallelAssetRow(CryptoSwapFifoParallelYearRow):
    asset: str


class CryptoSwapFifoParallelEventRow(BaseModel):
    year: int
    asset: str
    disposal_event_id: str
    source: str | None = None
    account: str | None = None
    tx_id: str | None = None
    current_gain_loss_eur: Decimal = Decimal("0")
    preview_gain_loss_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    current_proceeds_eur: Decimal = Decimal("0")
    preview_proceeds_eur: Decimal = Decimal("0")
    current_acquisition_cost_eur: Decimal = Decimal("0")
    preview_acquisition_cost_eur: Decimal = Decimal("0")
    current_tax_lines_count: int = 0
    preview_tax_lines_count: int = 0


class CryptoSwapFifoParallelPreviewReport(BaseModel):
    generated_at: str
    year: int | None = None
    status: Literal["matched", "delta", "unmatched_changed"]
    read_only: bool = True
    current_tax_lines_count: int = 0
    preview_tax_lines_count: int = 0
    current_lots_count: int = 0
    preview_lots_count: int = 0
    current_unmatched_disposals: int = 0
    preview_unmatched_disposals: int = 0
    current_gain_loss_eur: Decimal = Decimal("0")
    preview_gain_loss_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    absolute_year_gain_loss_delta_eur: Decimal = Decimal("0")
    affected_years: list[int] = Field(default_factory=list)
    years: list[CryptoSwapFifoParallelYearRow] = Field(default_factory=list)
    top_assets: list[CryptoSwapFifoParallelAssetRow] = Field(default_factory=list)
    top_events: list[CryptoSwapFifoParallelEventRow] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    current_policy: str
    preview_policy: str
    methodology: str


class CryptoSwapFifoParallelRunRequest(BaseModel):
    limit: int = 100
