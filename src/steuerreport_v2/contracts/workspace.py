"""Lesende Bedienvertraege; keine neue Steuer- oder Freigaberegel."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from steuerreport_v2.contracts.events import CanonicalEvent, EventType
from steuerreport_v2.contracts.product_readiness import ProductReadinessReport
from steuerreport_v2.contracts.review import ReviewGate
from steuerreport_v2.contracts.review import ReviewTask, ReviewTaskCategory, ReviewTaskPriority
from steuerreport_v2.contracts.sources import SourceConnectorAttempt, SourceDetail


class ActivityQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["events", "ledger"] = "events"
    year: int | None = Field(default=None, ge=2000, le=2100)
    start: date | None = None
    end: date | None = None
    source_ref: str | None = Field(default=None, pattern=r"^s_[a-f0-9]{20}$")
    asset: str | None = Field(default=None, max_length=128)
    event_type: EventType | None = None
    hint: Literal["all", "present", "none"] = "all"
    search: str = Field(default="", max_length=200)
    sort: Literal["newest", "oldest"] = "newest"
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: Literal[10, 25, 50, 100] = 25

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("activity_date_range_invalid")
        return self


class ActivityRow(BaseModel):
    row_id: str
    event: CanonicalEvent
    has_hint: bool
    corrected: bool
    ledger_asset: str | None = None
    ledger_quantity: Decimal | None = None
    ledger_account: str | None = None


class ActivityPage(BaseModel):
    generated_at: datetime
    rows: list[ActivityRow]
    total: int
    page: int
    page_size: int
    pages: int
    mode: Literal["events", "ledger"]
    timezone: str = "Europe/Berlin"
    hint_scope: str = "Unbekannter Ereignistyp, fehlender Rohbeleg oder nicht zugeordneter FIFO-Abgang; keine vollstaendige Review-Freigabe."


class ActivityExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: ActivityQuery = Field(default_factory=ActivityQuery)
    scope: Literal["filtered", "selected", "all"]
    selected_ids: list[str] = Field(default_factory=list, max_length=1000)


class ActivityDetail(BaseModel):
    event: CanonicalEvent
    raw: dict[str, object] | None = None
    ledger: list[dict[str, object]] = Field(default_factory=list)
    tax_lines: list[dict[str, object]] = Field(default_factory=list)
    corrections: list[dict[str, object]] = Field(default_factory=list)
    decisions: list[dict[str, object]] = Field(default_factory=list)
    ledger_count: int = 0
    tax_lines_count: int = 0
    details_limit: int = 200
    transfer_relationship: str = "Keine automatische Zuordnung zu einem Transferpartner; Kandidaten separat pruefen."


class WorkspaceSource(BaseModel):
    ref: str
    label: str
    source_type: str
    legacy_source_id: str | None = None
    connector_id: str | None = None
    connection_status: str
    ownership_status: str = "not_assessed"
    last_success_at: datetime | None = None
    last_attempt: SourceConnectorAttempt | None = None
    freshness: str = "missing"
    value_eur: Decimal | None = None
    value_basis: str = "unavailable"
    ledger_value_eur: Decimal | None = None
    events_count: int = 0
    imports_count: int = 0
    issues_count: int = 0
    reconciliation_status: str = "not_assessed"
    can_sync: bool = False
    warning: str | None = None


class WorkspaceSources(BaseModel):
    generated_at: datetime
    sources: list[WorkspaceSource]
    events_count: int
    methodology: str


class WorkspaceSourceDetail(BaseModel):
    source: WorkspaceSource
    valuation: SourceDetail | None = None
    evidence: dict[str, object] = Field(default_factory=dict)


class WorkspaceStatus(BaseModel):
    generated_at: datetime
    year: int
    events_count: int
    year_events_count: int = 0
    imports_count: int
    balance_entries: int
    owned_sources_count: int
    last_import_at: datetime | None = None
    calculation_at: datetime | None = None
    calculation_stale: bool = False
    review: ReviewGate
    readiness: ProductReadinessReport
    preview_available: bool
    final_available: bool
    summary: str
    next_section: Literal["sources", "import", "dashboard", "review", "tax", "export"]
    next_action: str
    dimensions: dict[str, str]


class WorkspaceReviewQuery(BaseModel):
    task_id: str | None = Field(default=None, max_length=200)
    model_config = ConfigDict(extra="forbid")
    search: str = Field(default="", max_length=200)
    category: ReviewTaskCategory | None = None
    priority: ReviewTaskPriority | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: Literal[10, 25, 50, 100] = 25


class WorkspaceReviewItem(BaseModel):
    task: ReviewTask
    event_ids: list[str] = Field(default_factory=list)
    source_ref: str | None = None


class WorkspaceReviewPage(BaseModel):
    generated_at: datetime
    items: list[WorkspaceReviewItem]
    total: int
    page: int
    pages: int
    page_size: int
    blocking_total: int
    unfiltered_total: int
