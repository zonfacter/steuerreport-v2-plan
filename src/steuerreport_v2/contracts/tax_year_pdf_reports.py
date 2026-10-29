from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TaxYearPdfReportSummary(BaseModel):
    taxable_private_disposals_eur: Decimal
    taxable_disposal_proceeds_eur: Decimal
    acquisition_cost_eur: Decimal
    rewards_mining_staking_income_eur: Decimal
    derivative_pnl_eur: Decimal
    tax_free_private_disposals_eur: Decimal
    tax_free_lines_count: int


class TaxYearPdfTechnicalStatus(BaseModel):
    status: Literal["technical_only", "blocked"]
    technical_export_allowed: bool
    final_filing_allowed: Literal[False] = False
    review_issues_current_open: int
    review_issues_historical_open: int
    review_blocking_issues_open: int
    parity_release_ready: bool
    parity_unresolved_groups: int
    parity_blocking_groups: int


class TaxYearPdfReportFile(BaseModel):
    file_index: int = Field(ge=1)
    filename: str
    page_count: int = Field(ge=1, le=100)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    download_endpoint: str


class TaxYearPdfReportManifest(BaseModel):
    manifest_schema: Literal["tax_year_pdf_report_manifest_v1"] = "tax_year_pdf_report_manifest_v1"
    artifact_id: str
    year: int = Field(ge=2000, le=2100)
    created_at: datetime
    report_status: Literal["preview"] = "preview"
    final_filing_allowed: Literal[False] = False
    calculation_run_id: str
    derivative_run_id: str | None = None
    fifo_method: str
    input_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filing_summary_status: str
    filing_summary_export_ready: bool
    summary: TaxYearPdfReportSummary
    technical_status: TaxYearPdfTechnicalStatus
    tax_line_count: int = Field(ge=0)
    reward_asset_row_count: int = Field(ge=0)
    reward_missing_value_count: int = Field(ge=0)
    derivative_line_count: int = Field(ge=0)
    derivative_missing_price_count: int = Field(ge=0)
    unmatched_disposals: int = Field(ge=0)
    missing_price_groups: int = Field(ge=0)
    sections: list[str]
    source_read_models: list[str]
    methodology: str
    files: list[TaxYearPdfReportFile] = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaxYearPdfReportArtifact(BaseModel):
    manifest: TaxYearPdfReportManifest
    manifest_endpoint: str


class TaxYearPdfReportList(BaseModel):
    generated_at: datetime
    year: int = Field(ge=2000, le=2100)
    artifacts: list[TaxYearPdfReportArtifact] = Field(default_factory=list)
