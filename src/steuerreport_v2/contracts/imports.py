from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.pipeline import ImportRunResult
from steuerreport_v2.contracts.mexc_import import MexcImportOptions, MexcImportPreview

ImportStatus = Literal["created", "loaded", "normalized", "failed"]


class ImportBatchCreate(BaseModel):
    source: str = Field(min_length=1)
    filename: str | None = None
    file_hash: str | None = None


class ImportBatch(BaseModel):
    batch_id: str
    source: str
    filename: str | None = None
    file_hash: str | None = None
    status: ImportStatus
    created_at: datetime
    raw_object_count: int = 0


class RawObjectCreate(BaseModel):
    row_number: int | None = None
    payload_json: str


class RawObject(BaseModel):
    raw_object_id: str
    batch_id: str
    row_number: int | None = None
    payload_json: str
    created_at: datetime


class CsvImportPreview(BaseModel):
    source: str
    filename: str
    profile_label: str
    file_format: str = "csv"
    sheet_name: str | None = None
    sheet_names: list[str] = []
    row_count: int
    columns: list[str]
    matched_columns: dict[str, str | None]
    missing_required_groups: list[str]
    sample_rows: list[dict[str, str | None]]
    can_import: bool
    duplicate_batch_id: str | None = None
    file_sha256: str | None = None
    import_fingerprint: str | None = None
    mexc: MexcImportPreview | None = None


ImportAssistantMode = Literal["file", "api", "onchain", "v1_cache"]


class ImportAssistantRequest(BaseModel):
    source: str = Field(min_length=1)
    import_mode: ImportAssistantMode = "file"
    filename: str | None = None
    content: str | None = None
    content_base64: str | None = None
    sheet_name: str | None = None
    mexc: MexcImportOptions | None = None


class ImportAssistantPriceNeed(BaseModel):
    asset: str
    years: list[int] = Field(default_factory=list)
    latest_price_available: bool = False


class ImportAssistantTaxImpact(BaseModel):
    estimated_new_rows: int = 0
    estimated_normalizable_rows: int = 0
    detected_assets: list[str] = Field(default_factory=list)
    detected_years: list[int] = Field(default_factory=list)
    duplicate_batch_id: str | None = None
    expected_review_issue_codes: list[str] = Field(default_factory=list)


class ImportAssistantPipelineSnapshot(BaseModel):
    import_batches: int = 0
    raw_objects: int = 0
    canonical_events: int = 0
    balance_entries: int = 0
    tax_lines: int = 0
    derivative_lines: int = 0
    review_issues_open: int = 0
    allow_export: bool = False


class ImportAssistantExecutionPlan(BaseModel):
    writes_database: bool = False
    requires_confirmation: bool = True
    will_create_batch: bool = False
    will_normalize_batch: bool = False
    will_rebuild_pipeline: bool = False
    affected_tables: list[str] = Field(default_factory=list)
    trace_url_template: str | None = None
    note: str


class ImportAssistantLinkedPreflight(BaseModel):
    label: str
    endpoint: str
    method: str = "GET"
    writes_database: bool = False
    external_requests: bool = False
    purpose: str
    next_step: str


class ImportAssistantPreview(BaseModel):
    source: str
    import_mode: ImportAssistantMode
    can_execute: bool
    blocked_reason: str | None = None
    preview: CsvImportPreview | None = None
    price_needs: list[ImportAssistantPriceNeed] = Field(default_factory=list)
    tax_impact: ImportAssistantTaxImpact
    current_state: ImportAssistantPipelineSnapshot | None = None
    estimated_state: ImportAssistantPipelineSnapshot | None = None
    execution_plan: ImportAssistantExecutionPlan | None = None
    linked_preflights: list[ImportAssistantLinkedPreflight] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportAssistantExecuteResult(BaseModel):
    preview: ImportAssistantPreview
    batch: ImportBatch
    run: ImportRunResult
