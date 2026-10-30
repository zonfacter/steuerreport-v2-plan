"""Quellengebundener Abruf, isolierte Vorschau und explizite Importfreigabe."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from steuerreport_v2.contracts.review import ReviewDecision


class HistoryRateState(BaseModel):
    available: bool = False
    config_revision: int | None = None
    requests_per_second: int | None = None
    requests_per_10_seconds: int | None = None
    requests_per_minute: int | None = None
    max_concurrency: int | None = None
    effective_max_requests_per_second: float | None = None
    budget_groups: list[str] = Field(default_factory=list)
    bottlenecks: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    waiting_requests: int | None = None
    in_flight: int | None = None
    wait_seconds: float | None = None
    retry_at: datetime | None = None


class HistoryRpcOption(BaseModel):
    id: Literal["public", "helius", "alchemy", "custom", "legacy"]
    label: str
    kind: Literal["public", "configured", "legacy"]
    provider_id: str | None = None
    configured: bool = False
    ready: bool = False
    blocked_reason: str | None = None
    pinned: bool = True
    tariff_verified: Literal[False] = False
    limits: HistoryRateState | None = None


class HistoryProgress(BaseModel):
    phase: Literal["discovery", "fetch", "preparing", "complete", "paused", "cancelled", "error", "unknown"] = "unknown"
    references_discovered: int | None = Field(default=None, ge=0)
    signatures_discovered: int | None = Field(default=None, ge=0)
    signatures_total: int | None = Field(default=None, ge=0)
    signatures_completed: int | None = Field(default=None, ge=0)
    addresses_completed: int | None = Field(default=None, ge=0)
    addresses_total: int | None = Field(default=None, ge=0)
    inventory_complete: bool = False
    fetch_elapsed_seconds: float | None = Field(default=None, ge=0)
    observed_details_per_second: float | None = Field(default=None, gt=0)
    estimated_fetch_remaining_seconds: int | None = Field(default=None, ge=0)
    estimate_status: Literal["unknown_total", "warming_up", "estimated", "paused", "fetch_complete", "not_supported", "unavailable"] = "unknown_total"
    estimate_scope: Literal["available_rpc_transaction_details"] = "available_rpc_transaction_details"
    updated_at: datetime | None = None


class HistoryCapability(BaseModel):
    source_ref: str
    label: str
    provider: str | None = None
    supported: bool = False
    ready: bool = False
    blocked_reason: str | None = None
    requires_symbols: bool = False
    supports_binance_earn: bool = False
    coverage_notes: list[str] = Field(default_factory=list)
    default_start: date = date(2020, 1, 1)
    rpc_options: list[HistoryRpcOption] = Field(default_factory=list)


class HistoryStart(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_id: UUID
    confirm_external_request: Literal[True]
    start: date = date(2020, 1, 1)
    end: date | None = None
    symbols: list[str] = Field(default_factory=list, max_length=200)
    include_binance_earn: StrictBool = False
    public_rpc_only: StrictBool = True
    rpc_provider: Literal["public", "helius", "alchemy", "custom"] | None = None
    max_records: int = Field(default=100000, ge=1, le=1000000)

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("history_external_confirmation_required")
        return value

    @field_validator("symbols")
    @classmethod
    def symbol_names(cls, values):
        import re
        result = list(dict.fromkeys(value.strip().upper() for value in values))
        if any(not re.fullmatch(r"[A-Z0-9_/-]{2,40}", value) for value in result):
            raise ValueError("history_symbols_invalid")
        return result

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end is not None and self.end < self.start:
            raise ValueError("history_date_range_invalid")
        if self.rpc_provider is not None and self.public_rpc_only != (self.rpc_provider == "public"):
            raise ValueError("history_rpc_choice_conflict")
        return self


class HistoryResume(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    confirm_external_request: Literal[True]
    max_records: int | None = Field(default=None, ge=1, le=1000000)

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("history_external_confirmation_required")
        return value


class HistoryApprove(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    actor: str = Field(min_length=1, max_length=120)
    confirm_import: Literal[True]
    confirm_recalculation: Literal[True]

    @field_validator("actor")
    @classmethod
    def named_reviewer(cls, value):
        if not value.strip():
            raise ValueError("history_actor_required")
        return value.strip()

    @field_validator("confirm_import", "confirm_recalculation", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("history_import_confirmation_required")
        return value


class BinanceSpotMatchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    batch_id: str | None = None
    filename: str | None = Field(default=None, min_length=1, max_length=240)
    content: str | None = None
    content_base64: str | None = None
    sheet_name: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        existing = self.batch_id is not None
        uploaded = self.filename is not None and (self.content is not None) != (self.content_base64 is not None)
        if existing == uploaded:
            raise ValueError("history_match_source_invalid")
        return self


class BinanceSpotMatchPreviewRequest(BinanceSpotMatchSource):
    pass


class BinanceSpotMatchDecisionCreate(BinanceSpotMatchSource):
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    csv_row_number: int = Field(ge=1)
    api_record_identity: str = Field(min_length=1, max_length=500)
    actor: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=8, max_length=2000)
    confirm_match: Literal[True]

    @field_validator("actor", "rationale")
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError("history_match_review_text_required")
        return value.strip()

    @field_validator("confirm_match", mode="before")
    @classmethod
    def explicit_match(cls, value):
        if value is not True:
            raise ValueError("history_match_confirmation_required")
        return value


class BinanceSpotMatchRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    actor: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=8, max_length=2000)

    @field_validator("actor", "rationale")
    @classmethod
    def non_blank(cls, value):
        if not value.strip():
            raise ValueError("history_match_review_text_required")
        return value.strip()


class BinanceSpotMatchFinancialFacts(BaseModel):
    event_time_utc: str
    event_type: str
    asset: str
    quantity: str
    quote_asset: str | None = None
    quote_quantity: str | None = None
    fee_asset: str | None = None
    fee_quantity: str | None = None


class BinanceSpotMatchCandidate(BaseModel):
    csv_row_number: int
    csv_provider_record_id: str | None = None
    symbol: str | None = None
    api_record_identity: str | None = None
    csv_financial_sha256: str | None = None
    api_financial_sha256: str | None = None
    csv_financial_facts: BinanceSpotMatchFinancialFacts | None = None
    api_financial_facts: BinanceSpotMatchFinancialFacts | None = None
    decision_id: str | None = None
    decision_state: Literal["none", "active", "revoked"] = "none"
    status: Literal[
        "matchable", "missing_stable_id", "symbol_missing", "api_record_missing",
        "csv_id_ambiguous", "api_id_ambiguous", "financial_digest_conflict",
        "financial_shape_unsupported", "already_decided", "match_revoked",
    ]


class BinanceSpotMatchPreview(BaseModel):
    provider: Literal["binance"] = "binance"
    connection_id: UUID
    job_id: UUID
    file_sha256: str
    source_batch_id: str | None = None
    preview_sha256: str
    candidates: list[BinanceSpotMatchCandidate] = Field(default_factory=list)


class BinanceSpotMatchDecisionResult(BaseModel):
    decision: ReviewDecision
    status: Literal["active", "revoked"]


class HistoryJob(BaseModel):
    requires_repreview: bool = False
    id: UUID
    source_ref: str
    label: str
    provider: str
    status: Literal["queued", "running", "paused", "ready", "importing", "succeeded", "failed", "cancelled"]
    phase: str
    created_at: datetime
    updated_at: datetime
    start: date
    end: date
    records_fetched: int = 0
    pages_fetched: int = 0
    new_records: int = 0
    duplicate_records: int = 0
    imported_events: int = 0
    requests: int = 0
    includes_binance_earn: bool = False
    provider_requests_reserved: int = Field(default=0, ge=0)
    provider_request_limit: int = Field(default=10000, ge=1)
    max_records: int = 100000
    preview_sha256: str | None = None
    sample_rows: list[dict[str, object]] = Field(default_factory=list)
    before_summary: dict[str, object] | None = None
    after_summary: dict[str, object] | None = None
    review_issues_open: int | None = None
    error_code: str | None = None
    coverage_notes: list[str] = Field(default_factory=list)
    complete_history_proven: bool = False
    can_resume: bool = False
    approval: dict[str, object] | None = None
    transport: HistoryRpcOption | None = None
    progress: HistoryProgress | None = None


class HistoryView(BaseModel):
    capability: HistoryCapability
    jobs: list[HistoryJob] = Field(default_factory=list)
