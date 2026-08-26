from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class BitgetStrategyReferencePrice(BaseModel):
    asset: str
    requested_at: datetime
    price_eur: Decimal | None = None
    priced_at: datetime | None = None
    source: str | None = None
    confidence: Decimal | None = None
    age_hours: Decimal | None = None
    same_day: bool = False
    independent: bool = False
    status: Literal["ready", "derived_review", "stale_review", "missing"]


class BitgetStrategyDisposalReconstruction(BaseModel):
    settlement_group_id: str
    source_event_id: str
    event_time: datetime
    asset: str
    acquisition_window_start: datetime
    acquisition_window_end: datetime
    minimum_holding_days: Decimal
    maximum_holding_days: Decimal
    holding_period_certainty: Literal[
        "definitely_within_one_year",
        "definitely_over_one_year",
        "crosses_one_year_boundary",
        "invalid_time_order",
    ]
    disposal_quantity: Decimal
    allocated_strategy_quantity: Decimal
    attributable_disposal_quote_asset: str | None = None
    attributable_disposal_quote_quantity: Decimal | None = None
    disposal_quote_price: BitgetStrategyReferencePrice | None = None
    attributable_disposal_proceeds_eur: Decimal | None = None
    documented_cost_basis_floor_eur: Decimal = Decimal("0")
    documented_cost_basis_ceiling_eur: Decimal | None = None
    zero_basis_gain_sensitivity_eur: Decimal | None = None
    settlement_value_proxy_basis_eur: Decimal | None = None
    settlement_value_proxy_gain_sensitivity_eur: Decimal | None = None
    tax_basis_status: Literal["provider_fill_basis_missing"] = (
        "provider_fill_basis_missing"
    )
    productive_tax_effect: Literal["none"] = "none"
    evidence_refs: list[str] = Field(default_factory=list)


class BitgetStrategyBasisReconstructionGroup(BaseModel):
    settlement_group_id: str
    year: int
    asset: str
    strategy_id: str
    strategy_type: str
    acquisition_window_start: datetime
    acquisition_window_end: datetime
    settlement_at: datetime
    settlement_quantity: Decimal
    supported_principal_carried_quantity: Decimal
    strategy_quantity_without_cost_basis: Decimal
    allocated_missing_quantity: Decimal
    residual_quantity: Decimal
    quantity_reconciled: bool
    strategy_investment_reference_usdt: Decimal
    strategy_reported_gain_reference_usdt: Decimal
    settlement_reference_value_usdt: Decimal | None = None
    strategy_investment_reference_eur: Decimal | None = None
    strategy_reported_gain_reference_eur: Decimal | None = None
    settlement_reference_value_eur: Decimal | None = None
    allocated_settlement_value_proxy_eur: Decimal | None = None
    attributable_disposal_proceeds_eur: Decimal | None = None
    documented_cost_basis_floor_eur: Decimal = Decimal("0")
    documented_cost_basis_ceiling_eur: Decimal | None = None
    zero_basis_gain_sensitivity_eur: Decimal | None = None
    settlement_value_proxy_gain_sensitivity_eur: Decimal | None = None
    investment_reference_price: BitgetStrategyReferencePrice
    gain_reference_price: BitgetStrategyReferencePrice
    settlement_reference_price: BitgetStrategyReferencePrice
    linked_disposals: list[BitgetStrategyDisposalReconstruction] = Field(
        default_factory=list
    )
    price_evidence_complete: bool = False
    basis_reconstruction_status: Literal[
        "ready_for_professional_review",
        "blocked_missing_strategy_match",
        "blocked_missing_reference_price",
    ]
    tax_basis_use: Literal["sensitivity_only_not_fifo_cost_basis"] = (
        "sensitivity_only_not_fifo_cost_basis"
    )
    productive_tax_effect: Literal["none"] = "none"
    evidence_refs: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class BitgetStrategyBasisReconstructionReport(BaseModel):
    run_id: str
    generated_at: datetime
    as_of: datetime
    source_run_input_fingerprint_digest: str
    source_gap_semantic_sha256: str
    status: Literal[
        "no_gap",
        "ready_for_professional_review",
        "blocked_missing_inputs",
    ]
    strict_ready: bool = False
    read_only: bool = True
    productive_tables_unchanged: bool = True
    productive_tax_effect: Literal["none"] = "none"
    provider_export_field_gap: bool = False
    support_package_complete: bool = False
    groups_count: int = 0
    linked_disposals_count: int = 0
    quantity_reconciled_groups_count: int = 0
    price_evidence_complete_groups_count: int = 0
    definitely_within_one_year_disposals_count: int = 0
    definitely_over_one_year_disposals_count: int = 0
    uncertain_holding_period_disposals_count: int = 0
    attributable_disposal_proceeds_total_eur: Decimal = Decimal("0")
    documented_cost_basis_floor_total_eur: Decimal = Decimal("0")
    documented_cost_basis_ceiling_total_eur: Decimal | None = None
    settlement_value_proxy_basis_total_eur: Decimal = Decimal("0")
    zero_basis_gain_sensitivity_total_eur: Decimal = Decimal("0")
    settlement_value_proxy_gain_sensitivity_total_eur: Decimal = Decimal("0")
    groups: list[BitgetStrategyBasisReconstructionGroup] = Field(
        default_factory=list
    )
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str


class BitgetStrategyReferencePriceBackfillRequest(BaseModel):
    execute: bool = False
    timeout_seconds: int = Field(default=20, ge=3, le=60)
    run_id: str | None = None


class BitgetStrategyReferencePriceBackfillJob(BaseModel):
    asset: Literal["USDT"] = "USDT"
    requested_date: date
    provider_rate_date: date | None = None
    usd_eur: Decimal | None = None
    status: Literal["planned", "imported", "already_ready", "fetch_failed"]
    request_url: str | None = None
    response_sha256: str | None = None
    price_source: str | None = None
    reason: str


class BitgetStrategyReferencePriceBackfillResult(BaseModel):
    generated_at: datetime
    source_run_id: str
    execute: bool = False
    status: Literal["planned", "applied", "partial", "blocked"]
    read_only: bool = True
    requested_dates_count: int = 0
    planned_count: int = 0
    imported_count: int = 0
    already_ready_count: int = 0
    failed_count: int = 0
    productive_tax_component_sha256_before: str
    productive_tax_component_sha256_after: str
    productive_tax_tables_unchanged: bool = False
    jobs: list[BitgetStrategyReferencePriceBackfillJob] = Field(default_factory=list)
    artifact_path: str
    semantic_sha256: str
    evidence_artifact_path: str
    evidence_artifact_sha256: str
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
