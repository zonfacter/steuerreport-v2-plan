from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ExportKind = Literal["pdf"]
ExportStatus = Literal["created", "blocked"]


class PdfExportRequest(BaseModel):
    label: str = Field(default="steuerreport")
    estimated_pages: int = Field(ge=0)


class ExportPackage(BaseModel):
    package_id: str
    kind: ExportKind
    label: str
    file_index: int
    page_count: int
    status: ExportStatus
    block_reason: str | None = None
    created_at: datetime
    filing_status: Literal["unbound", "preview"] = "unbound"
    input_binding_sha256: str | None = None
    calculation_run_id: str | None = None


class ExportResult(BaseModel):
    packages: list[ExportPackage]
    max_pages_per_file: int
    blocked: bool


class ExportReadiness(BaseModel):
    allow_export: bool
    review_issues_open: int
    review_issues_current_open: int = 0
    review_issues_historical_open: int = 0
    review_issues_open_total: int = 0
    review_blocking_issues_open: int = 0
    review_issues_high_open: int
    parity_release_ready: bool = True
    parity_unresolved_groups: int = 0
    parity_blocking_groups: int = 0
    parity_blocking_difference_eur: str = "0"
    parity_accepted_groups: int = 0
    parity_groups_total: int = 0
    tax_lines_count: int
    derivative_lines_count: int = 0
    derivative_realized_pnl_eur: str = "0"
    derivative_missing_price_count: int = 0
    unmatched_disposals: int
    latest_tax_run_id: str | None = None
    latest_derivative_run_id: str | None = None
    max_pdf_pages_per_file: int
    technical_export_allowed: bool = False
    final_filing_allowed: bool = False
    filing_status: Literal["technical_only", "blocked"] = "blocked"


class ExportPackageDeleteResult(BaseModel):
    package_id: str
    deleted: bool
