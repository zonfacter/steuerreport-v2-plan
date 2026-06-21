from __future__ import annotations

from datetime import date
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

PriceGapDecisionStatus = Literal[
    "unreviewed",
    "price_source_needed",
    "manual_price_required",
    "parser_data_needed",
    "not_tax_relevant",
    "price_added",
]
PriceQualityDecisionStatus = Literal[
    "unreviewed",
    "accepted_event_quote",
    "external_price_required",
    "manual_review_required",
]


class MissingPriceCoverageItem(BaseModel):
    scope: str
    asset: str
    year: int
    source: str
    event_type: str
    role: str
    decision_status: PriceGapDecisionStatus = "unreviewed"
    decision_id: str | None = None
    decision_title: str | None = None
    event_count: int
    first_event_at: datetime
    last_event_at: datetime
    gross_quantity: Decimal
    sample_event_ids: list[str]


class PriceCoverageReport(BaseModel):
    missing_count: int
    missing_assets: list[str]
    missing: list[MissingPriceCoverageItem]


class PriceRequirementItem(BaseModel):
    asset: str
    price_date: date
    year: int
    source: str
    event_type: str
    role: str
    event_count: int
    first_event_at: datetime
    last_event_at: datetime
    gross_quantity: Decimal
    sample_event_ids: list[str]


class PriceRequirementReport(BaseModel):
    requirements_count: int
    missing_assets: list[str]
    requirements: list[PriceRequirementItem]


class PriceQualityGroup(BaseModel):
    asset: str
    year: int
    source: str
    status: str
    risk_level: Literal["low", "medium", "high"]
    price_count: int
    low_confidence_count: int = 0
    proxy_count: int = 0
    zero_or_negative_count: int = 0
    min_confidence: Decimal
    avg_confidence: Decimal
    first_priced_at: datetime
    last_priced_at: datetime
    tax_lines_count: int = 0
    tax_quantity: Decimal = Decimal("0")
    evidence: str
    next_action: str
    scope: str
    decision_status: PriceQualityDecisionStatus = "unreviewed"
    decision_id: str | None = None
    decision_title: str | None = None


class PriceQualitySourceSummary(BaseModel):
    source: str
    price_count: int
    assets_count: int
    years_count: int
    low_confidence_count: int = 0
    proxy_count: int = 0
    tax_lines_count: int = 0
    risk_level: Literal["low", "medium", "high"]


class PriceQualityLatestAsset(BaseModel):
    asset: str
    price_eur: Decimal
    priced_at: datetime
    source: str
    confidence: Decimal
    status: str
    risk_level: Literal["low", "medium", "high"]


class PriceQualityPriceSample(BaseModel):
    asset: str
    price_eur: Decimal
    priced_at: datetime
    source: str
    confidence: Decimal
    event_id: str | None = None
    event_source: str | None = None
    event_type: str | None = None
    event_asset: str | None = None
    event_quantity: Decimal | None = None
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    source_ref: str | None = None
    raw_object_id: str | None = None


class PriceQualityTaxSample(BaseModel):
    tax_line_id: str
    asset: str
    disposed_at: datetime
    quantity: Decimal
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_days: int
    source_event_id: str
    lot_id: str


class PriceQualityGroupDetail(BaseModel):
    asset: str
    year: int
    source: str
    group: PriceQualityGroup | None = None
    price_samples: list[PriceQualityPriceSample] = Field(default_factory=list)
    tax_line_samples: list[PriceQualityTaxSample] = Field(default_factory=list)
    event_sources: dict[str, int] = Field(default_factory=dict)
    quote_assets: dict[str, int] = Field(default_factory=dict)
    methodology: str


class PriceQualityDecisionCreate(BaseModel):
    asset: str = Field(min_length=1)
    year: int
    source: str = Field(min_length=1)
    decision_status: PriceQualityDecisionStatus
    title: str
    rationale: str
    evidence_ref: str | None = None


class PriceQualityDecisionResult(BaseModel):
    decision_id: str
    scope: str
    decision_status: PriceQualityDecisionStatus


class PriceQualityManualReviewItem(BaseModel):
    scope: str
    asset: str
    year: int
    source: str
    priority_rank: int
    review_bucket: str
    evidence_ref: str
    decision_id: str | None = None
    decision_title: str | None = None
    price_count: int
    tax_lines_count: int
    tax_quantity: Decimal
    status: str
    risk_level: Literal["low", "medium", "high"]
    event_sources: dict[str, int] = Field(default_factory=dict)
    quote_assets: dict[str, int] = Field(default_factory=dict)
    sample_event_refs: list[str] = Field(default_factory=list)
    reason: str
    next_action: str


class PriceQualityManualReviewReport(BaseModel):
    generated_at: datetime
    manual_groups_count: int
    tax_relevant_groups_count: int
    total_tax_lines_count: int
    groups: list[PriceQualityManualReviewItem] = Field(default_factory=list)
    methodology: str


class PriceQualityStablecoinFxItem(BaseModel):
    scope: str
    asset: str
    year: int
    source: str
    price_count: int
    tax_lines_count: int
    tax_quantity: Decimal
    decision_id: str | None = None
    decision_title: str | None = None
    current_decision_status: PriceQualityDecisionStatus = "manual_review_required"
    expected_price_basis: str
    recommended_action: str
    evidence_ref: str
    event_sources: dict[str, int] = Field(default_factory=dict)
    quote_assets: dict[str, int] = Field(default_factory=dict)
    sample_event_refs: list[str] = Field(default_factory=list)
    reason: str


class PriceQualityStablecoinFxReport(BaseModel):
    generated_at: datetime
    groups_count: int
    tax_relevant_groups_count: int
    total_tax_lines_count: int
    assets: list[str] = Field(default_factory=list)
    groups: list[PriceQualityStablecoinFxItem] = Field(default_factory=list)
    methodology: str


class PriceQualitySolscanSignatureItem(BaseModel):
    scope: str
    asset: str
    year: int
    source: str
    price_count: int
    tax_lines_count: int
    tax_quantity: Decimal
    decision_id: str | None = None
    decision_title: str | None = None
    current_decision_status: PriceQualityDecisionStatus = "manual_review_required"
    signature_count: int = 0
    non_signature_ref_count: int = 0
    signature_refs: list[str] = Field(default_factory=list)
    non_signature_refs: list[str] = Field(default_factory=list)
    event_sources: dict[str, int] = Field(default_factory=dict)
    quote_assets: dict[str, int] = Field(default_factory=dict)
    reason: str
    recommended_action: str
    evidence_ref: str


class PriceQualitySolscanSignatureReport(BaseModel):
    generated_at: datetime
    groups_count: int
    tax_relevant_groups_count: int
    total_tax_lines_count: int
    total_signature_refs: int
    assets: list[str] = Field(default_factory=list)
    groups: list[PriceQualitySolscanSignatureItem] = Field(default_factory=list)
    methodology: str


class PriceQualityBinanceNormalizerItem(BaseModel):
    scope: str
    asset: str
    year: int
    source: str
    price_count: int
    tax_lines_count: int
    tax_quantity: Decimal
    decision_id: str | None = None
    decision_title: str | None = None
    current_decision_status: PriceQualityDecisionStatus = "manual_review_required"
    has_missing_quote_fields: bool = False
    has_unknown_events: bool = False
    has_zero_quantity_samples: bool = False
    sample_ref_count: int = 0
    missing_sample_refs: bool = False
    sample_event_refs: list[str] = Field(default_factory=list)
    event_sources: dict[str, int] = Field(default_factory=dict)
    quote_assets: dict[str, int] = Field(default_factory=dict)
    reason: str
    recommended_action: str
    evidence_ref: str


class PriceQualityBinanceNormalizerReport(BaseModel):
    generated_at: datetime
    groups_count: int
    tax_relevant_groups_count: int
    total_tax_lines_count: int
    missing_quote_groups_count: int
    unknown_or_zero_groups_count: int
    missing_sample_ref_groups_count: int
    assets: list[str] = Field(default_factory=list)
    groups: list[PriceQualityBinanceNormalizerItem] = Field(default_factory=list)
    methodology: str


class PriceQualityEventQuoteEvidenceItem(BaseModel):
    scope: str
    asset: str
    year: int
    source: str
    price_count: int
    tax_lines_count: int
    tax_quantity: Decimal
    decision_id: str | None = None
    decision_title: str | None = None
    current_decision_status: PriceQualityDecisionStatus = "manual_review_required"
    evidence_class: str
    stable_quote_evidence: bool = False
    sample_ref_count: int = 0
    missing_sample_refs: bool = False
    sample_event_refs: list[str] = Field(default_factory=list)
    event_sources: dict[str, int] = Field(default_factory=dict)
    quote_assets: dict[str, int] = Field(default_factory=dict)
    reason: str
    recommended_action: str
    evidence_ref: str


class PriceQualityEventQuoteEvidenceReport(BaseModel):
    generated_at: datetime
    groups_count: int
    tax_relevant_groups_count: int
    total_tax_lines_count: int
    stable_quote_groups_count: int
    missing_sample_ref_groups_count: int
    assets: list[str] = Field(default_factory=list)
    groups: list[PriceQualityEventQuoteEvidenceItem] = Field(default_factory=list)
    methodology: str


class PriceQualityReport(BaseModel):
    generated_at: datetime
    price_points_count: int
    assets_count: int
    sources_count: int
    low_confidence_count: int
    proxy_count: int
    zero_or_negative_count: int
    tax_relevant_issue_groups: int
    issue_groups_count: int
    high_risk_groups: int
    medium_risk_groups: int
    low_risk_groups: int
    groups: list[PriceQualityGroup] = Field(default_factory=list)
    source_summaries: list[PriceQualitySourceSummary] = Field(default_factory=list)
    latest_assets: list[PriceQualityLatestAsset] = Field(default_factory=list)
    methodology: str


class PriceGapDecisionCreate(BaseModel):
    scope: str = Field(min_length=1)
    decision_status: PriceGapDecisionStatus
    title: str
    rationale: str
    evidence_ref: str | None = None


class PriceGapDecisionResult(BaseModel):
    decision_id: str
    scope: str
    decision_status: PriceGapDecisionStatus
