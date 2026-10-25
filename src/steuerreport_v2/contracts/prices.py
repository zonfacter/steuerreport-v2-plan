from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.divorce import DivorceValuationGate
from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.contracts.review import ReviewDecision


class PricePointCreate(BaseModel):
    asset: str
    price_eur: Decimal
    priced_at: datetime
    source: str
    confidence: Decimal = Decimal("1.0")


class PricePoint(PricePointCreate):
    price_id: str


class PriceDeleteResult(BaseModel):
    price_id: str
    deleted: bool


class PriceWriteResult(BaseModel):
    price: PricePoint
    pipeline: PipelineResult


class PriceCsvPreviewRow(BaseModel):
    row_number: int
    asset: str | None = None
    price_eur: Decimal | None = None
    priced_at: datetime | None = None
    source: str | None = None
    confidence: Decimal | None = None
    errors: list[str] = []


class PriceCsvPreview(BaseModel):
    row_count: int
    valid_rows: int
    invalid_rows: int
    can_import: bool
    required_columns: list[str]
    rows: list[PriceCsvPreviewRow]


class PriceCsvImportRequest(BaseModel):
    content: str
    default_source: str = "manual-price-csv"


class PriceCsvImportResult(BaseModel):
    imported_prices: int
    preview: PriceCsvPreview
    pipeline: PipelineResult | None = None


class V1FxCacheImportRequest(BaseModel):
    db_path: str = str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db"))
    confidence: Decimal = Decimal("1.0")


class V1FxCacheImportRow(BaseModel):
    asset: str
    price_date: date
    price_usd: Decimal
    usd_eur: Decimal
    price_eur: Decimal
    asset_source: str
    fx_source: str
    source_rate_date: str | None = None


class V1FxCacheImportPreview(BaseModel):
    db_path: str
    requirements_count: int
    importable_count: int
    missing_asset_usd_count: int
    missing_usd_eur_count: int
    importable: list[V1FxCacheImportRow]
    missing: list[dict[str, str]]


class V1FxCacheImportResult(BaseModel):
    imported_prices: int
    preview: V1FxCacheImportPreview
    pipeline: PipelineResult | None = None


class ExternalPriceBackfillRequest(BaseModel):
    config_path: str = "configs/crypto_price_sources.json"
    v1_fx_db_path: str = str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db"))
    provider: str = "auto"
    assets: list[str] = Field(default_factory=list)
    max_requests: int = 25
    timeout_seconds: int = 20
    confidence: Decimal = Decimal("1.0")
    dry_run: bool = True


class ExternalPriceBackfillJob(BaseModel):
    asset: str
    price_date: date
    provider_id: str | None = None
    status: str
    reason: str | None = None
    price_usd: Decimal | None = None
    usd_eur: Decimal | None = None
    price_eur: Decimal | None = None
    source: str | None = None


class ExternalPriceBackfillResult(BaseModel):
    requirements_count: int
    configured_assets: list[str]
    asset_filter: list[str]
    planned_jobs: int
    attempted: int
    imported_prices: int
    skipped: int
    failed: int
    dry_run: bool
    jobs: list[ExternalPriceBackfillJob]
    pipeline: PipelineResult | None = None


class CurrentPortfolioPriceBackfillRequest(BaseModel):
    config_path: str = "configs/crypto_price_sources.json"
    provider: str = "coingecko"
    assets: list[str] = Field(default_factory=list)
    max_requests: int = 50
    timeout_seconds: int = 20
    confidence: Decimal = Decimal("0.95")
    dry_run: bool = True


class CurrentPortfolioPriceBackfillJob(BaseModel):
    asset: str
    provider_id: str | None = None
    status: str
    reason: str | None = None
    price_eur: Decimal | None = None
    source: str | None = None


class CurrentPortfolioPriceBackfillResult(BaseModel):
    portfolio_assets_count: int
    configured_assets: list[str]
    asset_filter: list[str]
    planned_jobs: int
    attempted: int
    imported_prices: int
    skipped: int
    failed: int
    dry_run: bool
    priced_at: datetime
    jobs: list[CurrentPortfolioPriceBackfillJob]
    pipeline: PipelineResult | None = None


class AsOfPriceGateCandidate(BaseModel):
    asset: str
    accounts: list[str] = Field(default_factory=list)
    quantity: Decimal = Decimal("0")
    value_eur: Decimal = Decimal("0")
    current_price_eur: Decimal | None = None
    current_priced_at: datetime | None = None
    current_price_source: str | None = None
    current_price_age_days: int | None = None
    current_price_status: str
    provider_id: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str | None = None
    token_review_status: Literal["not_required", "pending", "accepted"] = "not_required"
    token_review_decision_id: str | None = None
    token_review_evidence_ref: str | None = None
    status: str
    reason: str


class AsOfPriceGateReport(BaseModel):
    generated_at: datetime
    as_of: datetime
    materiality_threshold_eur: Decimal
    strict_ready: bool = False
    status: str
    gate: DivorceValuationGate
    material_assets_count: int = 0
    requirements_count: int = 0
    fetchable_count: int = 0
    review_only_count: int = 0
    not_configured_count: int = 0
    candidates: list[AsOfPriceGateCandidate] = Field(default_factory=list)
    methodology: str


class AsOfTokenValuationDecisionRequest(BaseModel):
    as_of_date: date
    asset: str
    materiality_threshold_eur: Decimal = Field(default=Decimal("1"), ge=0)
    rationale: str | None = None
    actor: str = "user"


class AsOfTokenValuationDecisionResult(BaseModel):
    already_recorded: bool = False
    decision: ReviewDecision
    gate_after: AsOfPriceGateReport


class AsOfPriceGateBackfillRequest(BaseModel):
    as_of: datetime | None = None
    as_of_date: date | None = None
    materiality_threshold_eur: Decimal = Field(default=Decimal("1"), ge=0)
    config_path: str = "configs/crypto_price_sources.json"
    v1_fx_db_path: str = str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db"))
    provider: str = "defillama"
    assets: list[str] = Field(default_factory=list)
    max_requests: int = Field(default=25, ge=0, le=100)
    timeout_seconds: int = Field(default=20, ge=3, le=60)
    confidence: Decimal = Field(default=Decimal("0.99"), ge=0, le=1)
    dry_run: bool = True


class AsOfPriceGateBackfillJob(BaseModel):
    asset: str
    price_date: date
    provider_id: str | None = None
    status: str
    reason: str | None = None
    price_usd: Decimal | None = None
    usd_eur: Decimal | None = None
    price_eur: Decimal | None = None
    source: str | None = None


class AsOfPriceGateBackfillResult(BaseModel):
    generated_at: datetime
    dry_run: bool
    attempted: int = 0
    imported_prices: int = 0
    skipped: int = 0
    failed: int = 0
    gate_before: AsOfPriceGateReport
    gate_after: AsOfPriceGateReport
    jobs: list[AsOfPriceGateBackfillJob] = Field(default_factory=list)
    artifact_path: str
    methodology: str
