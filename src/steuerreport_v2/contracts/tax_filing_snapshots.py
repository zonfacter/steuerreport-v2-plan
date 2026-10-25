from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


TaxFilingSnapshotState = Literal["reference", "submitted"]
TaxFilingSnapshotKind = Literal["original", "correction"]
TaxFilingSnapshotIntegrity = Literal["verified", "missing", "mismatch"]


class TaxFilingValues(BaseModel):
    generated_at: str
    export_ready: bool
    taxable_private_disposals_eur: Decimal = Decimal("0")
    taxable_disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    tax_free_lines_count: int = 0


class TaxFilingSnapshotFile(BaseModel):
    path: str
    size_bytes: int
    sha256: str
    source_endpoint: str | None = None


class TaxFilingSnapshot(BaseModel):
    snapshot_id: str
    year: int
    revision: int
    state: TaxFilingSnapshotState
    filing_kind: TaxFilingSnapshotKind
    source_kind: str
    source_snapshot_id: str | None = None
    package_filename: str
    package_sha256: str
    package_size_bytes: int
    manifest_sha256: str
    runtime_fingerprint_sha256: str
    package_generated_at: str
    package_generated_at_europe_berlin: str | None = None
    created_at: str
    created_at_europe_berlin: str | None = None
    software_version: str = "unknown_at_capture"
    method_version: str = "unknown_at_capture"
    database_fingerprint_sha256: str | None = None
    submitted_at: str | None = None
    filing_usage_confirmed: bool = False
    filing_usage_confirmed_at: str | None = None
    filing_usage_confirmation_actor: str | None = None
    filing_usage_confirmation_source: str | None = None
    filing_usage_confirmation_statement: str | None = None
    note: str | None = None
    integrity_status: TaxFilingSnapshotIntegrity
    values: TaxFilingValues
    files_count: int = 0
    files: list[TaxFilingSnapshotFile] = Field(default_factory=list)
    package_download_endpoint: str


class TaxFilingSnapshotList(BaseModel):
    generated_at: str
    year: int | None = None
    snapshots: list[TaxFilingSnapshot] = Field(default_factory=list)
    submitted_count: int = 0
    reference_count: int = 0
    integrity_failures: int = 0
    methodology: str


class TaxFilingSnapshotCaptureRequest(BaseModel):
    state: TaxFilingSnapshotState = "reference"
    filing_kind: TaxFilingSnapshotKind = "original"
    submitted_at: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    confirmation_text: str | None = Field(default=None, max_length=120)
    source_snapshot_id: str | None = None


class TaxFilingSnapshotCaptureResult(BaseModel):
    created: bool
    snapshot: TaxFilingSnapshot
    comparison_endpoint: str
    message: str


class TaxFilingSnapshotUsageConfirmationRequest(BaseModel):
    statement: str = Field(min_length=10, max_length=2000)
    actor: str = Field(default="user", min_length=2, max_length=120)
    source: Literal["chat_user_statement", "web_ui", "api"] = "api"


class TaxFilingSnapshotUsageConfirmationResult(BaseModel):
    created: bool
    event_id: str
    snapshot: TaxFilingSnapshot
    comparison_endpoint: str
    message: str


class TaxFilingSnapshotDelta(BaseModel):
    key: str
    label: str
    category: Literal["declaration", "supporting", "informational"]
    filed_value_eur: Decimal
    current_value_eur: Decimal
    delta_eur: Decimal
    direction: Literal["increase", "decrease", "unchanged"]
    changed_at_cent_precision: bool
    requires_review: bool
    explanation: str


class TaxFilingSnapshotComparison(BaseModel):
    year: int
    generated_at: str
    baseline: TaxFilingSnapshot | None = None
    baseline_selection: Literal[
        "latest_submitted",
        "confirmed_used_reference",
        "latest_reference",
        "none",
    ]
    latest_reference: TaxFilingSnapshot | None = None
    unconfirmed_reference: TaxFilingSnapshot | None = None
    usage_confirmed_reference: TaxFilingSnapshot | None = None
    current_values: TaxFilingValues
    deltas: list[TaxFilingSnapshotDelta] = Field(default_factory=list)
    exact_change_detected: bool = False
    declaration_change_detected: bool = False
    amendment_review_required: bool = False
    submission_confirmation_required: bool = False
    submission_timestamp_required: bool = False
    integrity_blocked: bool = False
    status: Literal[
        "no_snapshot",
        "reference_confirmation_required",
        "submission_timestamp_required",
        "unchanged",
        "changed_review_required",
        "integrity_blocked",
    ]
    headline: str
    next_action: str
    legal_notice: str
    comparison_html_endpoint: str
    audit_report_endpoint: str | None = None
    methodology: str
