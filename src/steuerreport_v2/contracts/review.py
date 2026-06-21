from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ReviewSeverity = Literal["low", "medium", "high"]
ReviewTaskPriority = Literal["low", "medium", "high"]
ReviewTaskCategory = Literal["fifo", "price", "import", "wallet", "reconciliation", "evidence", "tax"]


class ReviewIssue(BaseModel):
    code: str
    severity: ReviewSeverity
    message: str
    scope: str
    blocks_export: bool
    tax_year: int | None = None
    is_current_scope: bool = True


class ReviewGate(BaseModel):
    allow_export: bool
    issues_open: int
    issues_open_total: int | None = None
    issues_current_open: int | None = None
    issues_historical_open: int = 0
    issues_high_open: int
    issues_medium_open: int = 0
    issues_low_open: int = 0
    blocking_issues_open: int = 0
    issues: list[ReviewIssue]


class ReviewDecisionCreate(BaseModel):
    decision_type: str
    scope: str
    title: str
    rationale: str
    evidence_ref: str | None = None
    actor: str = "user"
    source: str | None = None
    affected_ids: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class ReviewDecision(ReviewDecisionCreate):
    decision_id: str
    created_at: datetime
    updated_at: datetime | None = None


class ReviewDecisionSuggestion(ReviewDecisionCreate):
    suggestion_id: str
    confidence: str
    auto_persist: bool = False


class ReviewTask(BaseModel):
    task_id: str
    priority: ReviewTaskPriority
    category: ReviewTaskCategory
    title: str
    detail: str
    source: str
    scope: str
    action_label: str
    action_path: str | None = None
    blocks_export: bool = False
    tax_year: int | None = None
    asset: str | None = None
    source_group: str | None = None
    count: int | None = None
    value_eur: Decimal | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    decision_status: str | None = None
    token_name: str | None = None
    token_symbol: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str | None = None


class ReviewTaskSummary(BaseModel):
    generated_at: datetime
    open_tasks: int
    blocking_tasks: int
    high_priority_tasks: int
    medium_priority_tasks: int
    low_priority_tasks: int
    fifo_relevant_tasks: int
    evidence_tasks: int
    tasks: list[ReviewTask] = Field(default_factory=list)
    methodology: str


class ReviewEvidenceTraceItem(BaseModel):
    trace_id: str
    scope: str
    title: str
    status: str
    canonical_evidence_ref: str
    stored_evidence_ref: str | None = None
    decision_id: str | None = None
    decision_status: str
    evidence_trace_status: str | None = None
    import_effect: str = "none"
    target_changed: bool = False
    action_path: str
    note: str


class ReviewEvidenceTraceReport(BaseModel):
    generated_at: datetime
    traces_count: int = 0
    canonical_count: int = 0
    legacy_ref_count: int = 0
    missing_decision_count: int = 0
    traces: list[ReviewEvidenceTraceItem] = Field(default_factory=list)
    methodology: str


class ReviewEvidenceTraceCanonicalizeRequest(BaseModel):
    execute: bool = False


class ReviewEvidenceTraceCanonicalizeResult(BaseModel):
    execute: bool = False
    target_changed: bool = False
    dry_run: bool = True
    candidates_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    updated_decision_ids: list[str] = Field(default_factory=list)
    candidates: list[ReviewEvidenceTraceItem] = Field(default_factory=list)
    methodology: str
