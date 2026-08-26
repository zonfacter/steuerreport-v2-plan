from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


BmfEventPriceRemediationStatus = Literal[
    "planned",
    "applied",
    "partial",
    "blocked",
]
BmfEventPriceRemediationJobStatus = Literal[
    "planned",
    "imported",
    "already_ready",
    "not_configured",
    "request_limit",
    "token_risk_blocked",
    "fx_failed",
    "provider_failed",
]


class BmfEventPriceRemediationRunRequest(BaseModel):
    execute: bool = False
    include_roles: list[Literal["received", "given"]] = Field(
        default_factory=lambda: ["received", "given"],
        min_length=1,
    )
    max_jobs: int = Field(default=250, ge=1, le=1000)
    timeout_seconds: int = Field(default=20, ge=3, le=60)
    config_path: str = (
        "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json"
    )


class BmfEventPriceRemediationJob(BaseModel):
    asset: str
    price_date: date
    roles: list[Literal["received", "given"]] = Field(default_factory=list)
    affected_event_ids: list[str] = Field(default_factory=list)
    affected_event_ids_truncated: bool = False
    previous_qualities: list[str] = Field(default_factory=list)
    previous_sources: list[str] = Field(default_factory=list)
    token_risk_status: str | None = None
    provider_id: str | None = None
    provider_request_url: str | None = None
    provider_response_sha256: str | None = None
    provider_timestamp: datetime | None = None
    provider_confidence: Decimal | None = None
    price_usd: Decimal | None = None
    fx_request_url: str | None = None
    fx_response_sha256: str | None = None
    fx_rate_date: date | None = None
    usd_eur: Decimal | None = None
    price_eur: Decimal | None = None
    price_source: str | None = None
    price_confidence: Decimal | None = None
    price_id: str | None = None
    status: BmfEventPriceRemediationJobStatus
    reason: str


class BmfEventPriceRemediationReport(BaseModel):
    run_id: str
    generated_at: datetime
    status: BmfEventPriceRemediationStatus
    execute: bool = False
    read_only: bool = True
    event_evidence_run_id_before: str
    event_evidence_run_id_after: str | None = None
    productive_tax_component_sha256_before: str
    productive_tax_component_sha256_after: str
    productive_tax_tables_unchanged: bool = False
    price_points_count_before: int = 0
    price_points_count_after: int = 0
    requirements_count: int = 0
    jobs_returned: int = 0
    planned_count: int = 0
    imported_count: int = 0
    already_ready_count: int = 0
    failed_count: int = 0
    token_risk_blocked_count: int = 0
    request_limit_count: int = 0
    provider_requests_count: int = 0
    fx_requests_count: int = 0
    unique_assets: list[str] = Field(default_factory=list)
    unique_dates_count: int = 0
    before_review_events_count: int = 0
    before_derived_price_review_count: int = 0
    before_stale_price_review_count: int = 0
    after_review_events_count: int | None = None
    after_derived_price_review_count: int | None = None
    after_stale_price_review_count: int | None = None
    jobs: list[BmfEventPriceRemediationJob] = Field(default_factory=list)
    artifact_path: str
    latest_artifact_path: str
    evidence_artifact_path: str
    evidence_artifact_sha256: str
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
