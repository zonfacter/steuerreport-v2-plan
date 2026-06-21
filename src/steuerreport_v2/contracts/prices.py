from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.pipeline import PipelineResult


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
    db_path: str = "/root/.local/share/steuerreport/steuerreport.db"
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
    config_path: str = "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json"
    v1_fx_db_path: str = "/root/.local/share/steuerreport/steuerreport.db"
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
    config_path: str = "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json"
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
