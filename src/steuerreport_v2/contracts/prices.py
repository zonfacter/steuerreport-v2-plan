from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from steuerreport_v2.contracts.divorce import DivorceValuationGate
from steuerreport_v2.contracts.price_admissions import PriceAdmissionReport
from steuerreport_v2.contracts.price_time import PriceTimeAssessment
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


class PriceLookupCandidate(BaseModel):
    price: PricePoint
    rejection_reason: str | None = None
    selected: bool = False
    provenance_status: Literal["not_linked", "synthetic_fiat_identity"] = "not_linked"


class PriceLookupDecision(BaseModel):
    policy_id: str = "historical_same_utc_day_not_after_event"
    policy_version: int = 1
    asset: str
    event_time: datetime
    allow_derived: bool
    status: Literal["selected", "missing", "fiat"]
    rejection_reason: str | None = None
    selected_price: PricePoint | None = None
    candidates: list[PriceLookupCandidate] = Field(default_factory=list)
    candidate_count: int = 0
    candidates_truncated: bool = False


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


V1_FX_CACHE_BLOCK_CODE = "v1_fx_cache_import_blocked_unverified"
V1_FX_CACHE_BLOCK_MESSAGE = (
    "V1-Cache-Uebernahme gesperrt: Beleg, Kurszeit, Identitaet und "
    "unveraenderlicher Snapshot sind nicht geprueft. Die Vorschau zeigt nur Kandidaten."
)


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
    candidate_only: Literal[True] = True
    import_allowed: Literal[False] = False
    block_code: Literal["v1_fx_cache_import_blocked_unverified"] = V1_FX_CACHE_BLOCK_CODE
    block_reason: str = V1_FX_CACHE_BLOCK_MESSAGE
    requirements_count: int
    importable_count: int = Field(description="Anzahl unverbindlicher rechnerischer Kandidaten; keine Importfreigabe")
    missing_asset_usd_count: int
    missing_usd_eur_count: int
    importable: list[V1FxCacheImportRow] = Field(description="Unverbindliche Kandidaten; Beleg, Zeit, Identitaet und Snapshot sind nicht geprueft")
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
    request_id: UUID | None = Field(default=None, description="Kennung fuer einen bewusst neuen historischen Apply; Wiederholungen werden blockiert.")


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
    operation_kind: Literal["historical"] = "historical"
    requirements_count: int
    configured_assets: list[str]
    asset_filter: list[str]
    planned_jobs: int
    attempted: int
    imported_prices: int = Field(ge=0, strict=True)
    skipped: int
    failed: int
    dry_run: bool
    jobs: list[ExternalPriceBackfillJob]
    pipeline: PipelineResult | None = None
    stored_price_ids: list[str] = Field(default_factory=list, description="Beim erfolgreichen Speichern zurueckgegebene Preis-IDs, kein spaeterer Bestandsnachweis")
    pipeline_status: Literal["not_started", "completed", "failed"] = "not_started"
    pipeline_effects: Literal["not_started", "completed", "unknown_or_partial"] = "not_started"
    result_journal_status: Literal["not_started", "recorded", "unknown"] = "not_started"


class ExternalPriceBackfillStorageUnknown(BaseModel):
    storage_status: Literal["unknown"] = "unknown"
    pipeline_status: Literal["not_started"] = "not_started"


class CurrentPortfolioPriceBackfillRequest(BaseModel):
    config_path: str = "configs/crypto_price_sources.json"
    provider: str = "coingecko"
    assets: list[str] = Field(default_factory=list)
    max_requests: int = 50
    timeout_seconds: int = 20
    confidence: Decimal = Decimal("0.95")
    dry_run: bool = True
    request_id: UUID | None = Field(default=None, description="Eindeutige Kennung fuer einen bewusst neuen Apply; Wiederholungen derselben Kennung werden blockiert.")


class CurrentPortfolioPriceBackfillJob(BaseModel):
    asset: str
    provider_id: str | None = None
    status: str
    reason: str | None = None
    additional_reasons: list[str] = Field(default_factory=list)
    price_eur: Decimal | None = None
    source: str | None = None


class CurrentPortfolioPriceBackfillResult(BaseModel):
    operation_kind: Literal["current_portfolio"] = "current_portfolio"
    portfolio_assets_count: int
    configured_assets: list[str]
    asset_filter: list[str]
    planned_jobs: int
    attempted: int
    imported_prices: int = Field(ge=0, strict=True)
    skipped: int
    failed: int
    dry_run: bool
    priced_at: datetime
    jobs: list[CurrentPortfolioPriceBackfillJob]
    pipeline: PipelineResult | None = None
    stored_price_ids: list[str] = Field(default_factory=list, description="Bei Rueckkehr des Speicheraufrufs bestaetigte IDs; kein spaeterer Bestandsnachweis")
    pipeline_status: Literal["not_started", "completed", "failed"] = "not_started"
    pipeline_effects: Literal["not_started", "completed", "unknown_or_partial"] = "not_started"
    result_journal_status: Literal["not_started", "recorded", "unknown"] = "not_started"


class CurrentPortfolioPriceBackfillStatusRequest(BaseModel):
    request_id: UUID


class PriceBackfillCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[1] = 1
    operation_kind: Literal["current_portfolio", "historical"]
    stored_at: datetime
    stored_price_ids: list[str] = Field(max_length=1000)
    pipeline_status: Literal["not_started", "running_or_interrupted", "completed", "failed"]

    @field_validator("format_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("checkpoint_format_version_invalid")
        return value

    @field_validator("stored_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("checkpoint_timestamp_not_utc")
        return value.astimezone(UTC)

    @field_validator("stored_at", mode="before")
    @classmethod
    def timestamp_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("checkpoint_timestamp_invalid")
        return value

    @field_validator("stored_price_ids")
    @classmethod
    def canonical_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("checkpoint_price_ids_not_unique")
        for value in values:
            try:
                canonical = str(UUID(value))
            except ValueError:
                raise ValueError("checkpoint_price_id_invalid") from None
            if value != canonical:
                raise ValueError("checkpoint_price_id_not_canonical")
        return values

    @model_validator(mode="after")
    def operation_limit(self):
        if self.operation_kind == "current_portfolio" and len(self.stored_price_ids) > 250:
            raise ValueError("current_checkpoint_price_limit_exceeded")
        if not self.stored_price_ids and self.pipeline_status != "not_started":
            raise ValueError("empty_checkpoint_pipeline_invalid")
        return self


class CurrentPortfolioPriceBackfillStatus(BaseModel):
    status: Literal["recorded", "checkpointed", "unknown_or_running", "not_found"]
    result: CurrentPortfolioPriceBackfillResult | None = None
    checkpoint: PriceBackfillCheckpoint | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    explanation: str


class ExternalPriceBackfillStatusRequest(BaseModel):
    request_id: UUID


class ExternalPriceBackfillStatus(BaseModel):
    status: Literal["recorded", "checkpointed", "unknown_or_running", "not_found"]
    result: ExternalPriceBackfillResult | None = None
    checkpoint: PriceBackfillCheckpoint | None = None
    checkpoint_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    explanation: str


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
    price_time: PriceTimeAssessment
    price_admission: PriceAdmissionReport | None = None
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
    time_review_count: int = 0
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
